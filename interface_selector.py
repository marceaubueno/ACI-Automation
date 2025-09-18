# ---------------------------
# Developed by Marcelo Bueno & Chatgpt for Banco Pichincha 
# ---------------------------

import requests
import csv
import xml.etree.ElementTree as ET
import urllib3
import getpass
import argparse
import os
from datetime import datetime

# Disable Insecure Request Warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------
# Authenticate to APIC Controller
# ---------------------------
def authenticate_to_apic(apic_url, username, password):
    auth_url = f"https://{apic_url}/api/aaaLogin.json"
    auth_data = {"aaaUser": {"attributes": {"name": username, "pwd": password}}}
    headers = {"Content-Type": "application/json"}

    try:
        response = requests.post(auth_url, json=auth_data, headers=headers, verify=False, timeout=30)
        response.raise_for_status()
        return response.json()["imdata"][0]["aaaLogin"]["attributes"]["token"]
    except requests.exceptions.RequestException as e:
        print(f"Error during authentication: {e}")
        return None


# ---------------------------
# Fetch existing selectors per interface profile for pre Check
# ---------------------------
def get_existing_selectors(apic_url, auth_token):
    url = f"https://{apic_url}/api/node/class/infraHPortS.json"
    headers = {"Cookie": f"APIC-cookie={auth_token}"}

    try:
        response = requests.get(url, headers=headers, verify=False, timeout=30)
        response.raise_for_status()
        data = response.json()

        existing = {}
        for item in data.get("imdata", []):
            if "infraHPortS" not in item:
                continue
            attrs = item["infraHPortS"]["attributes"]
            dn = attrs.get("dn", "")
            selector_name = attrs.get("name", "")
            # dn example: uni/infra/accportprof-LF1102_INTPROF/hports-ISEL-1.10-typ-range
            if "accportprof-" in dn:
                try:
                    prof = dn.split("accportprof-")[1].split("/")[0]
                except IndexError:
                    continue
                existing.setdefault(prof, set()).add(selector_name)

        total = sum(len(v) for v in existing.values())
        print(f"Found {total} selectors across {len(existing)} profiles")
        return existing
    except requests.exceptions.RequestException as e:
        print(f"Error fetching existing selectors: {e}")
        return {}


# ---------------------------
# Build XML payload
# ---------------------------
def create_interface_profile_xml(interface_profile, selector_name, from_port, to_port, description):
    infra_acc_port_p = ET.Element("infraAccPortP", {
        "name": interface_profile,
        "dn": f"uni/infra/accportprof-{interface_profile}",
        "descr": description,
        "annotation": "",
        "ownerKey": "",
        "ownerTag": ""
    })

    infra_hport_s = ET.SubElement(infra_acc_port_p, "infraHPortS", {
        "name": selector_name,
        "type": "range",
        "annotation": "",
        "descr": description
    })

    # Hardcoded FEX ID
    ET.SubElement(infra_hport_s, "infraRsAccBaseGrp", {
        "fexId": "101",
        "tDn": ""
    })

    # Hardcoded fromCard="1" and toCard="1" for non-modular switches
    ET.SubElement(infra_hport_s, "infraPortBlk", {
        "name": selector_name,
        "descr": description,
        "fromCard": "1",
        "fromPort": from_port,
        "toCard": "1",
        "toPort": to_port
    })

    return ET.tostring(infra_acc_port_p, encoding="unicode")


# ---------------------------
# Push configuration to the APIC Controller | Dry Run before running the code
# ---------------------------
def push_configuration_to_apic(apic_url, auth_token, xml_data, interface_profile, dry_run=False):
    config_url = f"https://{apic_url}/api/node/mo/uni/infra/accportprof-{interface_profile}.xml"

    if dry_run:
        print(f"[DRY RUN] Would push config for {interface_profile}")
        return True

    headers = {"Content-Type": "application/xml", "Cookie": f"APIC-cookie={auth_token}"}
    try:
        response = requests.post(config_url, data=xml_data, headers=headers, verify=False, timeout=30)
        response.raise_for_status()
        print(f" Configuration for profile '{interface_profile}' pushed successfully!")
        return True
    except requests.exceptions.RequestException as e:
        print(f" Error while pushing configuration for {interface_profile}: {e}")
        if response is not None:
            print("APIC response:", response.text)
        return False


# ---------------------------
# Read CSV file and create config | We accept: , ; or spaces in the CSV file
# ---------------------------
def read_csv_and_create_config(csv_file, apic_url, auth_token, dry_run):
    summary = {"pushed": 0, "skipped": 0, "failed": 0, "skipped_names": []}
    details = []  # store per-row outcomes

    with open(csv_file, mode="r", encoding="utf-8-sig") as file:
        # Detect delimiter automatically
        sample = file.read(2048)
        file.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=[",", ";", "\t"])
        except csv.Error:
            dialect = csv.excel  # fallback to comma

        reader = csv.DictReader(file, dialect=dialect)

        headers = [h.strip() for h in reader.fieldnames]
        required_fields = [
            "interface_profile", "selector_name",
            "fromPort", "toPort",
            "description"
        ]
        missing_headers = [f for f in required_fields if f not in headers]
        if missing_headers:
            print(f"ERROR: Missing required CSV column(s): {missing_headers}")
            exit(1)
        
        # Prevalidation: We check for the existence of configured interface selectors in ACI, so we don't overwrite them!     
        existing_selectors = get_existing_selectors(apic_url, auth_token)

        for row in reader:
            interface_profile = row["interface_profile"]
            selector_name = row["selector_name"]

            if selector_name in existing_selectors.get(interface_profile, set()):
                msg = f" Skipped: selector '{selector_name}' already exists under profile '{interface_profile}'"
                print(msg)
                details.append(msg)
                summary["skipped"] += 1
                summary["skipped_names"].append(f"{interface_profile}:{selector_name}")
                continue

            try:
                xml_data = create_interface_profile_xml(
                    interface_profile, selector_name,
                    row["fromPort"], row["toPort"],
                    row["description"]
                )

                if push_configuration_to_apic(apic_url, auth_token, xml_data, interface_profile, dry_run):
                    msg = f" Pushed: selector '{selector_name}' under profile '{interface_profile}'"
                    summary["pushed"] += 1
                else:
                    msg = f" Failed: selector '{selector_name}' under profile '{interface_profile}'"
                    summary["failed"] += 1
            except Exception as e:
                msg = f" Failed to process selector '{selector_name}' under profile '{interface_profile}': {e}"
                summary["failed"] += 1

            print(msg)
            details.append(msg)

    # Build summary text
    summary_lines = [
        "\n========== SUMMARY ==========",
        f" Pushed (or dry-run simulated): {summary['pushed']}",
        f" Skipped (already exists): {summary['skipped']}",
    ]
    if summary["skipped_names"]:
        summary_lines.append("   Skipped selectors: " + ", ".join(summary["skipped_names"]))
    summary_lines.append(f" Failed: {summary['failed']}")
    summary_lines.append("=============================")
    summary_lines.append("\nPer-row details:")
    summary_lines.extend(details)
    summary_text = "\n".join(summary_lines)

    # Print to console
    print(summary_text)

    # Save to log file with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"summary_{timestamp}.log"
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(summary_text + "\n")
    print(f"\nSummary report saved to {os.path.abspath(log_file)}")


# ---------------------------
# Main execution
# ---------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push interface profiles to Cisco ACI via APIC")
    parser.add_argument("--csv", type=str, help="Path to the CSV file with interface profiles")
    parser.add_argument("--apic", type=str, help="APIC hostname or IP address")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads and URLs without pushing to APIC")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    apic_url = args.apic or input("Enter APIC hostname or IP: ").strip()
    csv_file = args.csv or input("Enter CSV file path: ").strip()

    print("Enter your APIC credentials:")
    username = input("Username: ")
    password = getpass.getpass("Password: ")

    print("Authenticating to APIC...")
    auth_token = authenticate_to_apic(apic_url, username, password)
    if not auth_token:
        print("Authentication failed. Exiting script.")
        exit()

    print("Authentication successful. Proceeding with config")
    read_csv_and_create_config(csv_file, apic_url, auth_token, DRY_RUN)
