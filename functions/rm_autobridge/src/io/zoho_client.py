import io
import time
import zipfile
import requests
import pandas as pd


# Maps Zoho CRM bulk-export API field names → canonical column names expected
# by CSVReader. Only fields used by the pipeline are listed; all others are
# dropped when the rename is applied.
ZOHO_COLUMN_MAP = {
    "Id": "Record Id",
    "Account_Name": "Property Name",
    "Property_Name_if_one_is_used": "Property Name if one is used",
    "Combined_Address": "Combined Address",
    "Maintenance_Membership_Package_and_Discount": "Maintenance Membership",
    "Drop_Down": "Membership Status",
    "Drain_and_Detail_Group": "Drain and Detail Group",
    "Standard_Service_Group": "Monthly Service Group",
    "Multi_Select_1": "Preferred Day of Week",
    "Property_Owners_Name": "Property Owners Name",
    "Property_Managers_Name": "Property Managers Name",
    "Prop_Management_Company": "Property Mgmt Company",
    "Prop_Owner_Phone": "Property Owners Phone",
    "Property_Manager_Phone_Number": "Property Managers Phone",
    "PM_Phone": "PM Phone",
    "Home_Access_Code": "Home Access Code",
    "Interior_Access_Info": "Home Access Instructions",
    "Neighborhood_Access": "Neighborhood Access Code",
    "Neighborhood_Access_Instructions": "Neighborhood Access Instructions",
    "Property_Access_Code": "Property Access Code",
    "Turn_By_Turn_Directions": "Turn By Turn Directions",
    "Internal_Notes": "Internal Notes for Techs Reference",
    "Sanitizer_Selection": "Sanitizer Selection",
    "Pre_Filter_Needed_for_Refill": "Pre-Filter Needed for Refill?",
    "Erosion_Drain_or_Special_Draining_Instructions": "Erosion Drain Special Instructions",
    "Must_Confirm_Appointment": "Must Confirm Drain and Detail",
}


class ZohoClient:
    def __init__(
        self,
        accounts_url: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        api_domain: str,
    ):

        self.api_domain = api_domain

        self.s = requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Zoho-oauthtoken {ZohoClient._get_access_token(accounts_url, refresh_token, client_id, client_secret)}",
                "Content-Type": "application/json",
            }
        )

    def get_properties(self) -> bytes:
        job_id = self._create_bulk_read_job()
        download_url = self._wait_for_job(job_id)
        zip_bytes = self._download(download_url)
        csv_bytes = self._extract_csv_bytes(zip_bytes)
        return self._normalize_columns(csv_bytes)

    def _normalize_columns(self, csv_bytes: bytes) -> bytes:
        """Rename Zoho API field names to canonical pipeline column names.

        Reads all columns as strings to prevent large IDs from being coerced
        to scientific notation floats. Resolves Property_Owners_Name lookup
        IDs to display names via a second Contacts API call.
        """
        df = pd.read_csv(io.BytesIO(csv_bytes), dtype=str)

        # Resolve owner lookup IDs → contact display names
        if "Property_Owners_Name" in df.columns:
            owner_ids = [
                v for v in df["Property_Owners_Name"].dropna().unique() if str(v).isdigit()
            ]
            if owner_ids:
                name_map = self._resolve_contact_names(owner_ids)
                df["Property_Owners_Name"] = df["Property_Owners_Name"].map(
                    lambda x: name_map.get(x, None) if pd.notna(x) else None
                )

        df = df.rename(columns=ZOHO_COLUMN_MAP)
        keep = [c for c in ZOHO_COLUMN_MAP.values() if c in df.columns]
        return df[keep].to_csv(index=False).encode()

    def _resolve_contact_names(self, contact_ids: list) -> dict:
        """Resolve Zoho Clients record IDs to Full_Name display text.

        Batches up to 100 IDs per request.
        Returns dict of {id_str: full_name}.
        """
        names = {}
        for i in range(0, len(contact_ids), 100):
            batch = contact_ids[i : i + 100]
            r = self.s.get(
                f"{self.api_domain}/crm/v8/Contacts",
                params={"ids": ",".join(batch), "fields": "Full_Name"},
            )
            if r.status_code == 204:
                continue
            r.raise_for_status()
            for record in r.json().get("data", []):
                names[str(record["id"])] = record.get("Full_Name") or ""
        return names

    @staticmethod
    def _get_access_token(
        accounts_url: str, refresh_token: str, client_id: str, client_secret: str
    ) -> str:

        url = (
            f"{accounts_url}/oauth/v2/token"
            f"?refresh_token={refresh_token}"
            f"&client_id={client_id}"
            f"&client_secret={client_secret}"
            f"&grant_type=refresh_token"
        )

        r = requests.post(url)
        r.raise_for_status()
        data = r.json()
        if "access_token" not in data:
            raise RuntimeError(f"Zoho token exchange failed: {data}")
        return data["access_token"]

    def _create_bulk_read_job(self) -> str:
        url = f"{self.api_domain}/crm/bulk/v8/read"

        payload = {
            "query": {
                "module": {"api_name": "Accounts"},
                "criteria": {
                    "field": {"api_name": "Drop_Down"},  # API name for Membership Status
                    "comparator": "in",
                    "value": ["Active Maintenance Member", "Complimentary Maintenance Member"],
                },
            }
        }

        r = self.s.post(url, json=payload)
        r.raise_for_status()
        data = r.json()["data"]
        return data[0]["details"]["id"]

    def _wait_for_job(self, job_id: str, timeout_sec: int = 300, poll_sec: int = 3) -> str:
        url = f"{self.api_domain}/crm/bulk/v8/read/{job_id}"
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            r = self.s.get(url)
            r.raise_for_status()
            job = r.json()["data"][0]
            state = job.get("state")
            if state == "COMPLETED":
                return job["result"]["download_url"]
            if state not in ("ADDED", "QUEUED", "IN PROGRESS", "COMPLETED"):
                raise RuntimeError(f"Zoho bulk read job {job_id} failed with state: {state}")
            time.sleep(poll_sec)
        raise TimeoutError(f"Zoho bulk read job {job_id} timed out after {timeout_sec}s")

    def _download(self, download_url: str) -> bytes:
        if download_url.startswith("/"):
            download_url = self.api_domain + download_url
        r = self.s.get(download_url)
        r.raise_for_status()
        return r.content

    def _extract_csv_bytes(self, zip_bytes: bytes) -> bytes:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError("Zoho export ZIP contained no CSV")
        return zf.read(names[0])
