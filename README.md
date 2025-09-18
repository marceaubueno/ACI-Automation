# ---------------------------
# This script is intended to configure Cisco ACI Port Selectors with a description only, for circumstances where you need to reserve and preconfigure ports on ACI leaf switches for future use. 
# ---------------------------
# Considerations:
# 1. We configure an interface selector with a port block and description
# 2. We configure a new interface profile, if doesn't exist yet
# 3. The code doesn't attach and interface policy group to the interface selector
# 4. We pre check for existing interface selectors, so we don't modify the existing ones
# 5. We present a summary report of the executed configuration 
# 6. All the configuration to be applied must be entered in a CSV file. The format is shown below.
# 7. You will need to provide the following information while running this code
#   7.1 APIC's ip address
#   7.2 APIC's credentials (username & password)
#   7.3 The full path to the CSV file
# ---------------------------
# Format of the CSV file
# interface_profile;selector_name;fromPort;toPort;description
# BladeServer;Port_Selector1;1;1;Selector for Blade Server 1
# ---------------------------
# To execute this script the package requests is needed. You can install it as shown bellow:
# C:\Python Projects\ACI> pip install requests
# ---------------------------
