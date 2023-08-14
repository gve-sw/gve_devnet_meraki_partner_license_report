#!/usr/bin/env python3
"""
Copyright (c) 2023 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied.
"""

__author__ = "Trevor Maco <tmaco@cisco.com>"
__copyright__ = "Copyright (c) 2023 Cisco and/or its affiliates."
__license__ = "Cisco Sample Code License, Version 1.1"

from datetime import datetime, date

import meraki
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress

from config import *

# Rich Console Instance
console = Console()

# Create a Meraki API client
dashboard = meraki.DashboardAPI(API_KEY, suppress_logging=True)


def get_days_remaining(expiration_date):
    """
    Return the difference in expiration date to the current day (for co-term orgs, per-device includes a duration field)
    :param expiration_date: Co-term license expiration date (format: 'Oct 6, 2025')
    :return: Remaining days in the license
    """
    current_date = datetime.utcnow()

    # Convert the date string to a datetime object
    target_date = datetime.strptime(expiration_date, '%b %d, %Y %Z')

    # Calculate the difference between the target date and the current date
    days_difference = (target_date - current_date).days

    # If difference is negative, licensed expired -> days remaining is N/A
    return str(days_difference) if days_difference > 0 else 'N/A'


def co_term_license(org_name, org_id):
    """
    Process Orgs with Co-term licensing, Extract relevant fields
    :param org_name: Org Name
    :param org_id: Org Id
    :return: Dictionary of license info
    """
    license_info = {'Org. Name': org_name, 'Org. ID': org_id, 'License Status': 'N/A', 'License Expiration': 'N/A',
                    'Days Remaining': 'N/A'}

    # Get License Overview from Org
    license_overview = dashboard.organizations.getOrganizationLicensesOverview(org_id)

    # License Status
    license_info['License Status'] = license_overview['status']

    # Expiration Date
    expiration_date = license_overview['expirationDate']
    license_info['License Expiration'] = license_overview['expirationDate'].replace('UTC', '').strip()

    # Calculate Days Remaining
    license_info['Days Remaining'] = get_days_remaining(expiration_date)

    return license_info


def per_device_license(org_name, org_id):
    """
    Process Orgs with per-device licensing, Extract relevant fields
    :param org_name: Org Name
    :param org_id: Org Id
    :return: Dictionary of license info
    """
    # Get License Overview from Org
    licenses = dashboard.organizations.getOrganizationLicenses(org_id, total_pages='all')

    per_device_licenses = []
    # Iterate through the list of licenses
    for license in licenses:
        license_info = {'Org. Name': org_name, 'Org. ID': org_id, 'License Type': license['licenseType'],
                        'License Status': license['state'], 'License Expiration': 'N/A', 'Days Remaining': 'N/A',
                        'Associated Device': 'N/A', 'Associated Network': 'N/A'}

        if license['expirationDate']:
            # Expiration Date
            expiration_date = license['expirationDate']

            datetime_obj = datetime.strptime(expiration_date, '%Y-%m-%dT%H:%M:%SZ')
            formatted_date = datetime_obj.strftime('%b %d, %Y')

            license_info['License Expiration'] = formatted_date

            # Calculate Days Remaining
            license_info['Days Remaining'] = license['durationInDays']

            # Associated Device (Serial)
            license_info['Associated Device'] = license['deviceSerial']

            # Associated Network
            license_info['Associated Network'] = dashboard.networks.getNetwork(license['networkId'])['name']

        per_device_licenses.append(license_info)

    return per_device_licenses


def output_file_name():
    """
    Generate timestamped output file name
    :return: Output file name
    """
    # Create destination file, include date stamp
    current_date = date.today()
    date_string = current_date.strftime("%m-%d-%Y")

    return f"meraki_license_report_{date_string}.xlsx"


def main():
    console.print(Panel.fit("Meraki Partner Licensing Report"))

    console.print(Panel.fit("GET a List of Orgs", title="Step 1"))
    # Get a list of organizations the user has access too
    orgs = dashboard.organizations.getOrganizations()
    console.print(f"[green]Found {len(orgs)} customers![/]")

    console.print(Panel.fit("Get License Information per Org", title="Step 2"))
    # Create lists, these will hold license dictionaries for each group of organization type
    coterm_licenses = []
    per_device_licenses = []

    with Progress() as progress:
        overall_progress = progress.add_task("Overall Progress", total=len(orgs), transient=True)
        counter = 1

        # Iterate through orgs, retrieve licensing information
        for org in orgs:
            progress.console.print("Processing Org: {} ({} of {})".format(org['name'], str(counter), len(orgs)))

            # License model (determines processing route)
            license_type = org['licensing']['model']

            if license_type == 'co-term':
                # If licence is co-term, use co-term API calls
                license_info = co_term_license(org['name'], org['id'])
                progress.console.print(
                    "- Found the Following Co-term Information: {}".format(license_info))

                coterm_licenses.append(license_info)
            elif license_type == 'per-device':
                # If licence is per-device, use per-device API call
                license_info = per_device_license(org['name'], org['id'])
                progress.console.print(
                    "- Found the Following Per-Device Information: {}".format(license_info))

                per_device_licenses.append(license_info)

            counter += 1
            progress.update(overall_progress, advance=1)

    # Create Report File
    console.print(Panel.fit("Generate Report", title="Step 3"))

    destination_file = output_file_name()
    console.print(f'Writing report to [blue]{destination_file}[/]...')

    with pd.ExcelWriter(destination_file) as writer:
        ### Co-term Sheet ###
        # Sort Licenses with the nearest Expiration Date at the top
        coterm_licenses_sorted = sorted(coterm_licenses,
                                        key=lambda item: datetime.strptime(item['License Expiration'], '%b %d, %Y') if
                                        item['License Expiration'] != 'N/A' else datetime.max)

        # Write Co-term License info to Excel
        coterm_licenses_df = pd.DataFrame(coterm_licenses_sorted)
        coterm_licenses_df.to_excel(writer, sheet_name='Co-term Customers', index=False)

        ### Per-Device Sheet(s) ###
        for org_licenses in per_device_licenses:
            # Sort Licenses with the nearest Expiration Date at the top
            org_licenses_sorted = sorted(org_licenses,
                                         key=lambda item: datetime.strptime(item['License Expiration'], '%b %d, %Y') if
                                         item['License Expiration'] != 'N/A' else datetime.max)

            # Write per-device License info to Excel
            org_licenses_df = pd.DataFrame(org_licenses_sorted)
            sheet_name = org_licenses_sorted[0]['Org. Name']
            org_licenses_df.to_excel(writer, sheet_name=sheet_name, index=False)

    console.print(f'- [green]Successfully wrote report[/]!')


if __name__ == "__main__":
    main()
