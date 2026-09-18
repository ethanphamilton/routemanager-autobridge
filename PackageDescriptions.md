# Maintenance package rules

Business rules of record for the membership tiers the scheduler expands. Each
entry's `Package Name` is the exact string that identifies a package in the CRM,
and is what `config/membership_tiers.yaml` routes on — exact-string matching,
with the fragility that implies (see "Brittle package routing" in the
[README](README.md#8-known-issues-and-operational-risks)).

> **Genericized for publication.** Package names here are representative, with
> the client's branding and pricing removed. The structure, cadences and
> scheduling rules are unchanged — they are what the handlers implement.

Two invariants hold across every tier:

- Drain jobs and Fill jobs MUST fall on the same day as one another.
- Neither may fall on the same day as a standard visit.

##  Package Name: "Annual Residential Package"

Details:

-   Receives 1 drain and detail every 12 months.

-   They need to receive 1 D&D and 0 standard visits each year.

-   Their dd_service_group will be 1-12 which corresponds to the month in which they receive their drain and detail (1=Jan, 12=Dec). 

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Semi-Annual Residential Package"

Details:

- Receives 1 Drain and Detail every 6 months.

- They need to receive 2 D&Ds and 0 standard visits each year.

- They have a dd_service_group (1-6) which assigns them 2 drain months per year (ex: [1, 6], [2, 7],...,[6, 12])

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Quarterly Residential Package"

Details:

- Receives 1 Drain and Detail every three months.

- They need to receive 4 D&Ds and 0 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    > - Group 1 receives D&Ds in Jan, April, July, Oct
    > - Group 2 receives D&Ds in Feb, May, Aug, Nov
    > - Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Monthly Residential Package"

Details:

- Receives 1 standard visit per month, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 8 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group number of 1-4.
    >- Group 1 receives their first visit in the first week of January
    >- Group 2 recieves their first visit in the second week of January
    >- Group 3 receives their first visit in the third week of January
    >- Group 4 receives their first visit in the fourth week of January

## Package Name: "Bi-Monthly Residential Package"
Details:

- Receives 1 standard visit every 2 weeks, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 22 standard visits per year.

- Their dd_service_group will be 1, 2, or 3. These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group which will be 1 or 2. 
    >- Group 1 gets their first visit of the year on the first week of Jan
    >- Group 2 gets their first visit of the year on the second week of Jan

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments in the RM UI.

## Package: "Weekly Residential Package"
Details:

- Receives 1 Standard visit per week, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 48 Standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Annual SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE ANNUAL RESIDENTIAL PACKAGE**

-   Receives 1 drain and detail every 12 months.

-   They need to receive 1 D&D and 0 standard visits each year.

-   Their dd_service_group will be 1-12 which corresponds to the month in which they receive their drain and detail (1=Jan, 12=Dec). 

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility
    should be for all days of the month except Saturdays and Sundays.

## Package Name: "Semi-Annual SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE SEMI-ANNUAL RESIDENTIAL PACKAGE**

- Receives 1 Drain and Detail every 6 months.

- They need to receive 2 D&Ds and 0 standard visits each year.

- They have a dd_service_group (1-6) which assigns them 2 drain months per year (ex: [1, 6], [2, 7],...,[6, 12])

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Quarterly SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE QUARTERLY RESIDENTIAL PACKAGE**

- Receives 1 Drain and Detail every three months.

- They need to receive 4 D&Ds and 0 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    > - Group 1 receives D&Ds in Jan, April, July, Oct
    > - Group 2 receives D&Ds in Feb, May, Aug, Nov
    > - Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Monthly SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE MONTHLY RESIDENTIAL PACKAGE**

- Receives 1 standard visit per month, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 8 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group number which is either 1 or 2.
    >- Group 1 receives their visit in the first half of the month.
    >- Group 2 receives their visit in the second half of the month.

-   They do not have a preferred day of the week. Their eligibility should be for all the days of the weeks corresponding to their monthly service group number except Saturdays and Sundays.

## Package Name: "Bi-Monthly SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE BI-MONTHLY RESIDENTIAL PACKAGE**

- Receives 1 standard visit every 2 weeks, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 22 standard visits per year.

- Their dd_service_group will be 1, 2, or 3. These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group which will be 1 or 2. 
    >- Group 1 gets their first visit of the year on the first week of Jan
    >- Group 2 gets their first visit of the year on the second week of Jan

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments in the RM UI.

## Package Name: "Weekly SwimSpa Residential Package"

Details:

**THIS IS IDENTICAL TO THE WEEKLY RESIDENTIAL PACKAGE**

- Receives 1 Standard visit per week, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 48 Standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Annual Residential Specialty Spa Maintenance Package"**

Details:

**THIS IS IDENTICAL TO THE OTHER ANNUAL RESIDENTIAL PACKAGES**

-   Receives 1 drain and detail every 12 months.

-   They need to receive 1 D&D and 0 standard visits each year.

-   Their dd_service_group will be 1-12 which corresponds to the month in which they receive their drain and detail (1=Jan, 12=Dec). 

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility
    should be for all days of the month except Saturdays and Sundays.

## Package Name: "Semi-Annual Residential Specialty Spa Maintenance Package"

Details:

**THIS IS IDENTICAL TO THE OTHER SEMI-ANNUAL RESIDENTIAL PACKAGES**

- Receives 1 Drain and Detail every 6 months.

- They need to receive 2 D&Ds and 0 standard visits each year.

- They have a dd_service_group (1-6) which assigns them 2 drain months per year (ex: [1, 6], [2, 7],...,[6, 12])

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Quarterly Residential Specialty Spa Maintenance Package"

Details:

**THIS IS IDENTICAL TO THE OTHER QUARTERLY RESIDENTIAL PACKAGES**

- Receives 1 Drain and Detail every three months.

- They need to receive 4 D&Ds and 0 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    > - Group 1 receives D&Ds in Jan, April, July, Oct
    > - Group 2 receives D&Ds in Feb, May, Aug, Nov
    > - Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They do not have a preferred day of the week. Their eligibility should be for all days of the month except Saturdays and Sundays.

## Package Name: "Monthly Residential Specialty Spa Maintenance Package"

Details:

**THIS IS IDENTICAL TO THE OTHER MONTHLY RESIDENTIAL PACKAGES**

- Receives 1 standard visit per month, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 8 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group number which is either 1 or 2.
    >- Group 1 receives their visit in the first half of the month.
    >- Group 2 receives their visit in the second half of the month.

-   They do not have a preferred day of the week. Their eligibility should be for all the days of the weeks corresponding to their monthly service group number except Saturdays and Sundays.

## Package Name: "Bi-Monthly Residential Specialty Spa Maintenance Package"

Details:

**THIS IS IDENTICAL TO THE OTHER BI-MONTHLY RESIDENTIAL PACKAGES**

- Receives 1 standard visit every 2 weeks, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 22 standard visits per year.

- Their dd_service_group will be 1, 2, or 3. These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group which will be 1 or 2. 
    >- Group 1 gets their first visit of the year on the first week of Jan
    >- Group 2 gets their first visit of the year on the second week of Jan

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments in the RM UI.

## Package Name: "Weekly Residential Specialty Spa Maintenance Package"

Details:

**THIS IS IDENTICAL TO THE OTHER WEEKLY RESIDENTIAL MAINTENANCE PACKAGES**

- Receives 1 Standard visit per week, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 48 Standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Once Weekly Vacation Rental"

Details:

- Receives 1 Standard visit per week, 1 drain and detail per month.

- They need to receive 12 D&Ds and 40 Standard visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of each month in which they receive their Drain and Detail.

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Weekly Residential Specialty Spa Maintenance Package with Monthly Drain and Details"

Details:

**THIS IS IDENTICAL TO THE ONCE WEEKLY VACATION RENTAL**

- Receives 1 Standard visit per week, 1 drain and detail per month.

- They need to receive 12 D&Ds and 40 Standard visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of each month in which they receive their Drain and Detail.

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Twice Weekly Vacation Rental"
Details:

- Receive 2 standard visits each week, 1 drain and detail (D&D) per month.

- They need to receive 12 D&Ds and 92 regular visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of the month in which they receive their Drain and Detail.

- These do not have a monthly service group number.

- They must have two preferred days of the week selected, and their visits will always take place on those two days of the week. If they have selected additional preferred days, the first and the last (furthest apart) will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "Once Weekly Specialty Spa Vacation Rental Maintenance"

Details:

**THIS IS IDENTICAL TO THE ONCE WEEKLY VACATION RENTAL**

- Receives 1 Standard visit per week, 1 drain and detail per month.

- They need to receive 12 D&Ds and 40 Standard visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of each month in which they receive their Drain and Detail.

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package: "Twice Weekly Specialty Spa Vacation Rental Maintenance"
Details:

**THIS IS IDENTICAL TO THE TWICE WEEKLY VACATION RENTAL**

- Receive 2 standard visits each week, 1 drain and detail (D&D) per month.

- They need to receive 12 D&Ds and 92 regular visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of the month in which they receive their Drain and Detail.

- These do not have a monthly service group number.

- They must have two preferred days of the week selected, and their visits will always take place on those two days of the week. If they have selected additional preferred days, the first and the last (furthest apart) will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package Name: "CUSTOM: Once Weekly Maintenance / Every Other Week Drain and Detail"**

Details:

-   Receives 1 standard visit each week, 1 drain and detail every other
    week.

-   They need to receive 26 D&Ds and 26 Standard visits per year.

-   The dd_service_group is always 13, reflecting the every other week
    D&D schedule.

-   There is no monthly service group number. Their D&D visit of the year will take place on the second week of Jan.

-   They must have 1 preferred day of the week selected and their visits
    will always take place on that day of the week. If they have
    selected additional preferred days, only the first will be used to
    generate their service order. Additional preferred days are used
    exclusively for manual schedule adjustments.

## Package Name: "PartnerAccount: Monthly Maintenance with Quarterly Drain and Details"

Details:

**THIS IS IDENTICAL TO MONTHLY RESIDENTIAL PACKAGE**

- Receives 1 standard visit per month, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 8 standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They have a monthly service group number which is either 1 or 2.
    >- Group 1 receives their visit in the first half of the month.
    >- Group 2 receives their visit in the second half of the month.

-   They do not have a preferred day of the week. Their eligibility should be for all the days of the weeks corresponding to their monthly service group number except Saturdays and Sundays.

## Package Name: "PartnerAccount: Once Weekly Maintenance with Monthly Drain and Details"**

Details:

**THIS IS IDENTICAL TO ONCE WEEKLY VACATION RENTAL**

- Receives 1 Standard visit per week, 1 drain and detail per month.

- They need to receive 12 D&Ds and 40 Standard visits per year.

- Their dd_service_group will be 1-4, corresponding to the week of each month in which they receive their Drain and Detail.

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.

## Package: "PartnerAccount: Once Weekly Maintenance with Quarterly Drain and Details"**

Details:

**THIS IS IDENTICAL TO WEEKLY RESIDENTIAL PACKAGE**

- Receives 1 Standard visit per week, 1 drain and detail per quarter.

- They need to receive 4 D&Ds and 48 Standard visits per year.

- Their dd_service_group will be 1-3, These correspond with:
    >- Group 1 receives D&Ds in Jan, April, July, Oct
    >- Group 2 receives D&Ds in Feb, May, Aug, Nov
    >- Group 3 receives D&Ds in Mar, June, Sept, Dec

- They do not have a monthly service group number.

- They must have 1 preferred day of the week selected and their visits will always take place on that day of the week. If they have selected additional preferred days, only the first will be used to generate their service order. Additional preferred days are used exclusively for manual schedule adjustments.