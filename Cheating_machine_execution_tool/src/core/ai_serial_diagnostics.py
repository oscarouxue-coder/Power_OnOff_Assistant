"""串口只读设备与驱动查询；不尝试打开串口，不推测外部占用者。"""
import json
import os

from src.core.ai_local_executor import run_local_command


def read_serial_status(target, stop, emit, internal=None):
    result = {"configured_com": target.port, "ports": [], "pnp": [], "external_owner": "未知",
              "internal": internal or {}, "notice": "管理员身份不排除访问限制；设备存在也不等于可打开。查询不打开COM。"}
    try:
        from serial.tools.list_ports import comports
        result["ports"] = [{"port": p.device, "description": p.description, "hwid": p.hwid,
                            "manufacturer": p.manufacturer, "serial_number": p.serial_number} for p in comports()]
        result["enumerated"] = any(p["port"].upper() == target.port.upper() for p in result["ports"])
    except Exception as exc:
        result["enumeration_error"] = str(exc)
    if os.name == "nt":
        script = """$ErrorActionPreference='Stop'
$drivers=@(Get-CimInstance Win32_PnPSignedDriver | Where-Object {$_.DeviceClass -eq 'PORTS'})
@(Get-CimInstance Win32_PnPEntity | Where-Object {$_.PNPClass -eq 'Ports'} | ForEach-Object {
  $device=$_; $driver=$drivers | Where-Object {$_.DeviceID -eq $device.PNPDeviceID} | Select-Object -First 1
  [PSCustomObject]@{name=$device.Name; instance_id=$device.PNPDeviceID; status=$device.Status;
    present=$device.Present; problem_code=$device.ConfigManagerErrorCode;
    driver_provider=$driver.DriverProviderName; driver_version=$driver.DriverVersion;
    driver_date=[string]$driver.DriverDate; driver_inf=$driver.InfName}
}) | ConvertTo-Json -Depth 4 -Compress
"""
        try:
            query = run_local_command(script, os.getcwd(), 60, stop, emit)
            if query["status"] != "completed" or query["exit_code"] != 0 or query["truncated"]:
                result["pnp_error"] = query
            else:
                value = json.loads(query["stdout"] or "[]")
                result["pnp"] = value if isinstance(value, list) else [value]
        except InterruptedError:
            raise
        except Exception as exc:
            result["pnp_error"] = str(exc)
    else:
        result["pnp_error"] = "仅Windows支持PnP/驱动查询"
    return result
