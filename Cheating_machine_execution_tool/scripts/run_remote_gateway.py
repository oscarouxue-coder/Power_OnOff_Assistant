"""Source gateway and explicit local pairing/scope management. No DUT operation entrypoints."""
import argparse
import getpass
import json
import os
from pathlib import Path
import ssl
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.remote_gateway_transport import GatewayConnection, GatewayWebSocketServer
from src.services.remote_gateway_store import RemoteGatewayStore
from src.services.remote_instance_identity import RemoteInstanceIdentity
from src.services.remote_gateway_runtime import RemoteInstanceConfig


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LineCheckAssistant" / "gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18761)
    serve.add_argument("--vpn", action="store_true")
    serve.add_argument("--certificate")
    serve.add_argument("--private-key")
    serve.add_argument("--platform-config-dir", type=Path, help="本机已配置并绑定群的DPAPI应用配置目录；不复制密钥")
    serve.add_argument("--platforms", default="", help="显式启用dingtalk、feishu，逗号分隔")
    pair = commands.add_parser("pair-code")
    pair.add_argument("--scope-file", type=Path, required=True, help="本地审阅后的聊天/成员允许范围JSON")
    revoke = commands.add_parser("revoke")
    revoke.add_argument("instance_id")
    for name in ("pair-instance", "allow-instance", "show-instance"):
        command = commands.add_parser(name)
        command.add_argument("--app-dir", type=Path, default=Path(__file__).resolve().parents[1])
        command.add_argument("--slot", type=int, default=1)
        if name == "pair-instance":
            command.add_argument("--url", required=True)
            command.add_argument("--name", required=True)
            command.add_argument("--vpn", action="store_true")
        elif name == "allow-instance":
            command.add_argument("--channels", required=True)
            command.add_argument("--capabilities", required=True)
            command.add_argument("--confirm-local-scope", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.command in ("pair-instance", "allow-instance", "show-instance"):
        identity = RemoteInstanceIdentity(args.app_dir, slot=args.slot)
        try:
            config = RemoteInstanceConfig(identity)
            if args.command == "pair-instance":
                pairing = GatewayConnection(args.url, vpn=args.vpn).pair(getpass.getpass("一次性配对码: "), identity.instance_id, args.name)
                config.save(dict(pairing, url=args.url, name=args.name, vpn=args.vpn, enabled=False,
                                 channel_ids=[], capability_ids=[]))
                print("配对成功，尚未授予远程执行权限。候选范围：")
                print(json.dumps(pairing["scopes"], ensure_ascii=False, indent=2))
            elif args.command == "allow-instance":
                value = config.load()
                channels = [int(n.strip()) for n in args.channels.split(",")]
                capabilities = [n.strip() for n in args.capabilities.split(",") if n.strip()]
                if not channels or any(not 1 <= n <= 16 for n in channels) or not capabilities:
                    raise ValueError("必须明确通道1至16及已开放能力ID")
                value.update(channel_ids=sorted(set(channels)), capability_ids=capabilities, enabled=True)
                config.save(value)
                print("本地接入范围已保存；远程新会话仍为请求批准，完全访问须在实例工作台单独确认。")
            else:
                value = config.load()
                value.pop("credential", None)
                print(json.dumps(dict(value, **identity.snapshot()), ensure_ascii=False, indent=2))
        finally:
            identity.close()
        return 0
    store = RemoteGatewayStore(args.directory)
    server = None
    platforms = None
    try:
        if args.command == "pair-code":
            print(store.create_pairing(json.loads(args.scope_file.read_text(encoding="utf-8-sig"))))
        elif args.command == "revoke":
            store.revoke(args.instance_id)
            print("已撤销指定实例的接入凭据")
        else:
            context = None
            if args.certificate or args.private_key:
                if not args.certificate or not args.private_key:
                    raise ValueError("TLS证书和私钥必须同时指定")
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                context.load_cert_chain(args.certificate, args.private_key)
            server = GatewayWebSocketServer(store, args.host, args.port, ssl_context=context, vpn=args.vpn, emit=print).start()
            if args.platforms:
                if args.platform_config_dir is None:
                    raise ValueError("启用平台必须指定已绑定应用配置目录")
                from src.services.dingtalk_remote_store import RemoteConfigStore
                from src.services.feishu_remote_store import FeishuConfigStore
                from src.services.remote_gateway_platforms import GatewayPlatforms
                factories = dict(dingtalk=RemoteConfigStore, feishu=FeishuConfigStore)
                configs = {}
                for name in args.platforms.split(","):
                    if name not in factories:
                        raise ValueError("平台只能为dingtalk或feishu")
                    config = factories[name](Path(__file__).resolve().parents[1], directory=args.platform_config_dir).load()
                    if not config.get("corp") or not config.get("group"):
                        raise ValueError("应用必须先在本机完成群绑定")
                    configs[name] = dict(config, enabled=True)
                    if name == "feishu":
                        configs[name]["group_enabled"] = True  # Explicit CLI platform opt-in; saved direct settings stay unchanged.
                platforms = GatewayPlatforms(store, configs, emit=print)
                platforms.start()
            while True:
                time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        if platforms:
            platforms.close()
        if server:
            server.close()
        store.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("统一入口操作失败，请检查地址、实例占用、范围及当前Windows用户凭据；未执行设备操作。", file=sys.stderr)
        raise SystemExit(1)
