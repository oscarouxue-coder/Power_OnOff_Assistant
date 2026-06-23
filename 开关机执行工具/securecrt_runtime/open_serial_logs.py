#$language = "Python3"
#$interface = "1.0"

import json


def main():
    if crt.Arguments.Count < 1:
        crt.Dialog.MessageBox("缺少串口连接配置文件。", "串口日志记录")
        return

    manifest_path = crt.Arguments.GetArg(0)
    with open(manifest_path, "r", encoding="utf-8") as manifest_file:
        manifest = json.load(manifest_file)

    errors = []
    for target in manifest.get("targets", []):
        connect_info = (
            "/SERIAL {port} /BAUD {baud} /DATA {data_bits} "
            "/PARITY {parity} /STOP {stop_bits} /NOCTS /NODSR /NOXON"
        ).format(**target)
        try:
            tab = crt.Session.ConnectInTab(connect_info, True, True)
            if not tab.Session.Connected:
                errors.append("{vlan} ({port}) 连接失败".format(**target))
                if tab.Index != crt.GetScriptTab().Index:
                    tab.Close()
                continue
            tab.Session.LogFileName = target["log_path"]
            tab.Session.Log(True, True, False)
            tab.Session.SetStatusText(
                "{vlan} / {port} / 日志记录中".format(**target)
            )
        except Exception as exc:
            errors.append("{vlan} ({port}): {error}".format(error=str(exc), **target))

    if errors:
        crt.Dialog.MessageBox("部分串口连接失败：

" + "
".join(errors), "串口日志记录")


main()
