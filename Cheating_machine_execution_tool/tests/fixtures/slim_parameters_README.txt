slim_parameters.xls is a small real BIFF8/OLE workbook generated once with xlwt 1.3.0.
It contains headers VLAN, SN, 2.4G SSID and one row:
vlan101, 001234567890, wifi_24_fixture (all stored as strings).
It verifies that the packaged xlrd path preserves leading zeros without NumPy/lxml.
xlwt is a fixture-generation tool, not a runtime or packaging dependency.
