import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from line_check_assistant.test_item_config_store import (
    ConnectWifiSettings,
    DEFAULT_COMMAND_FAIL_RETRY_INTERVAL,
    DEFAULT_ORDER_RETRY_TIMES,
    ExpectedSegment,
    ORDER_GLOBAL_RETRY_INTERVAL_KEY,
    OrderConfig,
    OrderItem,
    ProjectInfoSettings,
    TelnetSettings,
    TestItemConfigStore,
    TestProjectConfig,
)


class TestItemConfigStoreTests(unittest.TestCase):
    def test_load_defaults_when_config_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")

            loaded = store.load()

            # Telnet 段全部回退默认值
            self.assertEqual(loaded.telnet.request_url, "http://192.168.29.1")
            self.assertEqual(loaded.telnet.port, 23)
            self.assertEqual(loaded.telnet.user, "root")
            self.assertEqual(loaded.telnet.password, "")
            self.assertEqual(loaded.telnet.timeout, 10)
            self.assertEqual(loaded.telnet.input_user_flag, "ogin:")
            self.assertEqual(loaded.telnet.input_password_flag, "Password:")
            self.assertEqual(loaded.telnet.login_success_flag, "#")
            self.assertEqual(loaded.telnet.telnet_need_enter_password_flag, 0)
            self.assertEqual(loaded.telnet.telnet_no_user_password_flag, 0)
            self.assertEqual(loaded.telnet.only_power_off_on, 0)
            # telnet_default_on 新字段默认 1(默认勾选);老 ini 缺该 key 时也回退 1。
            self.assertEqual(loaded.telnet.telnet_default_on, 1)
            # [order] 段全局默认值 + 空列表
            self.assertEqual(loaded.order.command_fail_retry_interval_time, DEFAULT_COMMAND_FAIL_RETRY_INTERVAL)
            self.assertEqual(loaded.order.items, [])
            # [connect_wifi] 段默认值
            self.assertEqual(loaded.connect_wifi.enable, 0)
            self.assertEqual(loaded.connect_wifi.test_2g_enable, 1)
            self.assertEqual(loaded.connect_wifi.test_5g_enable, 1)
            self.assertEqual(loaded.connect_wifi.product_solution, "openwrt")
            self.assertEqual(loaded.connect_wifi.auth_mode, "WPA2-PSK")
            self.assertEqual(loaded.connect_wifi.cipher, "AES")
            self.assertEqual(loaded.connect_wifi.choose_wireless_card, 0)
            self.assertEqual(loaded.connect_wifi.wireless_card_name, "")
            # [project_info] 段缺省时 4 字段全部回退空串(Q1=A,仅编辑器)
            self.assertEqual(loaded.project_info.project_name, "")
            self.assertEqual(loaded.project_info.software_version, "")
            self.assertEqual(loaded.project_info.internal_software_version, "")
            self.assertEqual(loaded.project_info.onu_compile_time, "")

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            saved = TestProjectConfig(
                telnet=TelnetSettings(
                    request_url="http://192.168.10.1",
                    port=2223,
                    user="admin",
                    password="t*hEQ#BHu7z%%3n",
                    timeout=15,
                    input_user_flag="ogin:",
                    input_password_flag="Password:",
                    login_success_flag="$",
                    telnet_need_enter_password_flag=1,
                    telnet_no_user_password_flag=0,
                    only_power_off_on=0,
                    telnet_default_on=0,  # 显式关掉,验证非默认 1 也能往返
                ),
                order=OrderConfig(
                    command_fail_retry_interval_time=90,
                    items=[
                        OrderItem(
                            command="ifconfig ra0",
                            expected_segments=[
                                ExpectedSegment(text="00:00:00:00:00:00", negate=True),
                                ExpectedSegment(text="UP BROADCAST", negate=False),
                            ],
                            retry_times=5,
                        ),
                        OrderItem(
                            command="ip route show table main | grep default",
                            expected_segments=[ExpectedSegment(text="default via 172.172.172.1")],
                            retry_times=5,
                        ),
                    ],
                ),
                connect_wifi=ConnectWifiSettings(
                    enable=1,
                    test_2g_enable=0,
                    test_5g_enable=1,
                    product_solution="openwrt",
                    auth_mode="WPA3-PSK",
                    cipher="TKIP+AES",
                    choose_wireless_card=1,
                    wireless_card_name="Wi-Fi 2",
                ),
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.telnet, saved.telnet)
            # 新字段 telnet_default_on=0 落盘后必须能读回 0(非默认值 1 的对称 round-trip)。
            self.assertEqual(loaded.telnet.telnet_default_on, 0)
            # 落盘文本也必须包含 telnet_default_on
            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn("telnet_default_on = 0", content)
            self.assertEqual(loaded.order.command_fail_retry_interval_time, saved.order.command_fail_retry_interval_time)
            self.assertEqual(len(loaded.order.items), len(saved.order.items))
            for loaded_item, saved_item in zip(loaded.order.items, saved.order.items):
                self.assertEqual(loaded_item.command, saved_item.command)
                self.assertEqual(
                    [(seg.text, seg.negate) for seg in loaded_item.expected_segments],
                    [(seg.text, seg.negate) for seg in saved_item.expected_segments],
                )
                self.assertEqual(loaded_item.retry_times, saved_item.retry_times)
            self.assertEqual(loaded.connect_wifi, saved.connect_wifi)

    def test_save_mirrors_inverse_telnet_enable_to_legacy_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            legacy_config_path = config_dir / "config.ini"
            legacy_config_path.write_text(
                "[ui_defaults]\n"
                "# keep this comment\n"
                "telnet_enable = 1\n"
                "baud_rate = 19200\n",
                encoding="utf-8",
            )
            store = TestItemConfigStore(config_dir / "test_project_config.ini")

            store.save(TestProjectConfig(telnet=TelnetSettings(telnet_default_on=1)))
            enabled_content = legacy_config_path.read_text(encoding="utf-8")
            self.assertIn("telnet_enable = 0", enabled_content)
            self.assertIn("# keep this comment", enabled_content)

            store.save(TestProjectConfig(telnet=TelnetSettings(telnet_default_on=0)))
            disabled_content = legacy_config_path.read_text(encoding="utf-8")
            self.assertIn("telnet_enable = 1", disabled_content)
            self.assertIn("# keep this comment", disabled_content)

    def test_save_writes_retry_interval_only_to_legacy_other_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            legacy_config_path = config_dir / "config.ini"
            legacy_config_path.write_text(
                "[ui_defaults]\n"
                "telnet_enable = 0\n\n"
                "[other_config]\n"
                "# keep interval comment\n"
                "command_fail_retry_interval_time = 60\n"
                "command_fail_retry_success_times = 10\n",
                encoding="utf-8",
            )
            store = TestItemConfigStore(config_dir / "test_project_config.ini")

            store.save(
                TestProjectConfig(
                    order=OrderConfig(command_fail_retry_interval_time=25)
                )
            )
            test_project_content = (config_dir / "test_project_config.ini").read_text(
                encoding="utf-8"
            )
            legacy_content = legacy_config_path.read_text(encoding="utf-8")

        self.assertNotIn("command_fail_retry_interval_time", test_project_content)
        self.assertIn("command_fail_retry_interval_time = 25", legacy_content)
        self.assertIn("# keep interval comment", legacy_content)
        self.assertIn("command_fail_retry_success_times = 10", legacy_content)

    def test_save_omits_global_retry_interval_from_order_section(self):
        # [order] 只保存测试命令；全局重试间隔唯一写入 config.ini。
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(
                order=OrderConfig(
                    command_fail_retry_interval_time=42,
                    items=[
                        OrderItem(command="ls", expected_segments=[ExpectedSegment(text="file1")], retry_times=3),
                    ],
                ),
            )

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            order_section_start = content.find("[order]")
            order_section_end = content.find("[", order_section_start + 1)
            order_section_body = content[order_section_start:order_section_end]
            self.assertNotIn(ORDER_GLOBAL_RETRY_INTERVAL_KEY, order_section_body)
            self.assertIn("ls retry_times_3 = file1", order_section_body)
            legacy_content = (Path(temp_dir) / "config.ini").read_text(encoding="utf-8")
            self.assertIn("command_fail_retry_interval_time = 42", legacy_content)

    def test_load_reads_retry_interval_from_legacy_config_and_ignores_stale_order_key(self):
        # 即使旧测试项目仍残留同名 key，也必须以 config.ini 为唯一来源。
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_project_config.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            parser["order"] = {
                "command_fail_retry_interval_time": "33",
                "ifconfig ra0 retry_times_5": "UP BROADCAST",
            }
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)
            (Path(temp_dir) / "config.ini").write_text(
                "[other_config]\ncommand_fail_retry_interval_time = 120\n",
                encoding="utf-8",
            )

            loaded = TestItemConfigStore(config_path).load()
            self.assertEqual(loaded.order.command_fail_retry_interval_time, 120)
            self.assertEqual([item.command for item in loaded.order.items], ["ifconfig ra0"])

    def test_expected_segments_serialize_with_double_ampersand_join(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(
                order=OrderConfig(
                    items=[
                        OrderItem(
                            command="ifconfig pppoe-iface4",
                            expected_segments=[
                                ExpectedSegment(text="inet addr:172.172.172"),
                                ExpectedSegment(text="inet6 addr: 2001:172:101"),
                            ],
                            retry_times=5,
                        ),
                    ],
                ),
            )

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn(
                "inet addr:172.172.172&&inet6 addr: 2001:172:101",
                content,
                "多段期望值必须用 && 拼接",
            )

    def test_negate_prefix_serializes_with_bang(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(
                order=OrderConfig(
                    items=[
                        OrderItem(
                            command="ifconfig ra0",
                            expected_segments=[
                                ExpectedSegment(text="00:00:00:00:00:00", negate=True),
                                ExpectedSegment(text="UP BROADCAST", negate=True),
                            ],
                            retry_times=5,
                        ),
                    ],
                ),
            )

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn(
                "!00:00:00:00:00:00&&!UP BROADCAST",
                content,
                "两段都勾选否定时,每段都应加 ! 前缀",
            )

    def test_skip_empty_expected_segments_when_joining(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(
                order=OrderConfig(
                    items=[
                        OrderItem(
                            command="uptime",
                            expected_segments=[ExpectedSegment(text=""), ExpectedSegment(text="up")],
                            retry_times=3,
                        ),
                    ],
                ),
            )

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            # 空段不应出现在拼接结果中,也不应被 && 包裹
            self.assertIn("uptime retry_times_3 = up", content)

    def test_per_segment_negate_mixed_serialization(self):
        """per-segment 否定混合:首段否定、次段肯定 → ``!段A&&段B``。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(
                order=OrderConfig(
                    items=[
                        OrderItem(
                            command="ifconfig pppoe-iface4",
                            expected_segments=[
                                ExpectedSegment(text="inet addr:172.172.172", negate=True),
                                ExpectedSegment(text="inet6 addr: 2001:172:101", negate=False),
                                ExpectedSegment(text="UP BROADCAST", negate=True),
                            ],
                            retry_times=5,
                        ),
                    ],
                ),
            )

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn(
                "!inet addr:172.172.172&&inet6 addr: 2001:172:101&&!UP BROADCAST",
                content,
                "每段应独立加 ! 前缀,用 && 拼接",
            )

    def test_per_segment_negate_round_trip_mixed(self):
        """混合 negate 序列化后能正确读回,每段保留独立 negate。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            saved = TestProjectConfig(
                order=OrderConfig(
                    items=[
                        OrderItem(
                            command="bbfdmd -c get Device.ManagementServer.X_SDMC_AcsLineStatus",
                            expected_segments=[
                                ExpectedSegment(text="AcsLineStatus => 1", negate=False),
                                ExpectedSegment(text="offline", negate=True),
                            ],
                            retry_times=5,
                        ),
                    ],
                ),
            )

            store.save(saved)
            loaded = store.load()

            segments = loaded.order.items[0].expected_segments
            self.assertEqual(len(segments), 2)
            self.assertEqual(segments[0].text, "AcsLineStatus => 1")
            self.assertFalse(segments[0].negate)
            self.assertEqual(segments[1].text, "offline")
            self.assertTrue(segments[1].negate)

    def test_parse_per_segment_negate_helper(self):
        """``_split_expected`` 应按段独立解析 ``!`` 前缀。"""
        from line_check_assistant.test_item_config_store import _split_expected

        # 全部否定
        self.assertEqual(
            _split_expected("!A&&!B"),
            [(True, "A"), (True, "B")],
        )
        # 全部肯定
        self.assertEqual(
            _split_expected("A&&B"),
            [(False, "A"), (False, "B")],
        )
        # 混合
        self.assertEqual(
            _split_expected("!A&&B&&!C"),
            [(True, "A"), (False, "B"), (True, "C")],
        )
        # 单段否定
        self.assertEqual(
            _split_expected("!hello"),
            [(True, "hello")],
        )
        # 单段肯定
        self.assertEqual(
            _split_expected("hello"),
            [(False, "hello")],
        )
        # 空串
        self.assertEqual(_split_expected(""), [(False, "")])

    def test_parse_command_key_extracts_retry_times(self):
        # 单独验证 _parse_order_key 的两个分支
        from line_check_assistant.test_item_config_store import _parse_order_key

        command, retry = _parse_order_key("ifconfig ra0 retry_times_5")
        self.assertEqual(command, "ifconfig ra0")
        self.assertEqual(retry, 5)

        # 命令含管道和空格时也必须正确拆分
        command, retry = _parse_order_key("ip route show table main | grep default retry_times_7")
        self.assertEqual(command, "ip route show table main | grep default")
        self.assertEqual(retry, 7)

        # 缺 retry_times 后缀时回退默认值
        command, retry = _parse_order_key("ifconfig ra0")
        self.assertEqual(command, "ifconfig ra0")
        self.assertEqual(retry, DEFAULT_ORDER_RETRY_TIMES)

        # retry_times_0 视为无效,回退默认 5
        command, retry = _parse_order_key("uptime retry_times_0")
        self.assertEqual(retry, DEFAULT_ORDER_RETRY_TIMES)

    def test_parse_command_key_without_retry_times_defaults_to_five(self):
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_project_config.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            parser["order"] = {
                # 老 ini 可能未带 retry_times 后缀;此处确认回退默认 5。
                "ps": "PID",
            }
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)

            loaded = TestItemConfigStore(config_path).load()
            self.assertEqual(len(loaded.order.items), 1)
            self.assertEqual(loaded.order.items[0].command, "ps")
            self.assertEqual(loaded.order.items[0].retry_times, DEFAULT_ORDER_RETRY_TIMES)

    def test_special_characters_in_password_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            # 密码含 * # % 与 ini 解析特殊字符,验证 configparser 不丢失内容。
            config = TestProjectConfig(telnet=TelnetSettings(password="t*hEQ#BHu7z%%3n"))

            store.save(config)
            loaded = store.load()

            self.assertEqual(loaded.telnet.password, "t*hEQ#BHu7z%%3n")

    def test_load_tolerates_unknown_keys(self):
        # ini 出现未识别 key 时不应报错,应该被忽略
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_project_config.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            parser["telnet"] = {
                "request_url": "http://10.0.0.1",
                "future_field": "ignored",
            }
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)

            loaded = TestItemConfigStore(config_path).load()
            self.assertEqual(loaded.telnet.request_url, "http://10.0.0.1")
            # 缺省字段仍然回退默认值
            self.assertEqual(loaded.telnet.user, "root")
            # 老 ini 没有 telnet_default_on 时也回退默认 1(默认勾选)
            self.assertEqual(loaded.telnet.telnet_default_on, 1)

    def test_telnet_default_on_saves_as_zero_or_one(self):
        """telnet_default_on 字段统一 0/1,即便 UI 传入 Python bool 也强制转换。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            for raw_value, expected in ((1, "1"), (0, "0"), (True, "1"), (False, "0")):
                config = TestProjectConfig(telnet=TelnetSettings(telnet_default_on=raw_value))
                store.save(config)
                with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                    content = file.read()
                self.assertIn(
                    f"telnet_default_on = {expected}",
                    content,
                    f"raw_value={raw_value}",
                )

    def test_connect_wifi_enable_serializes_as_zero_or_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            for raw_enable, expected in ((1, "1"), (0, "0"), (True, "1"), (False, "0")):
                config = TestProjectConfig(connect_wifi=ConnectWifiSettings(enable=raw_enable))
                store.save(config)
                with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                    content = file.read()
                self.assertIn(f"enable = {expected}", content, f"raw_enable={raw_enable}")

    def test_product_solution_lowercased_on_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            config = TestProjectConfig(connect_wifi=ConnectWifiSettings(product_solution="OpenWrt"))

            store.save(config)

            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn("product_solution = openwrt", content)

    def test_project_info_save_and_load_round_trip(self):
        """4 字段含中文 / 空格 / 常见符号时往返保留。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = TestItemConfigStore(Path(temp_dir) / "test_project_config.ini")
            saved = TestProjectConfig(
                project_info=ProjectInfoSettings(
                    project_name="SDMC ONT 自动化",
                    software_version="V1.0.2-beta",
                    internal_software_version="S13.58.01.001",
                    onu_compile_time="2026-07-19 18:30",
                )
            )

            store.save(saved)
            loaded = store.load()

            self.assertEqual(loaded.project_info, saved.project_info)
            # 落盘文本也必须包含四行字段
            with (Path(temp_dir) / "test_project_config.ini").open("r", encoding="utf-8") as file:
                content = file.read()
            self.assertIn("[project_info]", content)
            self.assertIn("project_name = SDMC ONT 自动化", content)
            self.assertIn("software_version = V1.0.2-beta", content)
            self.assertIn("internal_software_version = S13.58.01.001", content)
            self.assertIn("onu_compile_time = 2026-07-19 18:30", content)

    def test_project_info_load_tolerates_missing_section(self):
        """老 ini 没有 [project_info] 段时,4 字段全部回退空串,不抛 NoSectionError。"""
        from configparser import RawConfigParser

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "test_project_config.ini"
            parser = RawConfigParser()
            parser.optionxform = str
            # 故意不写 [project_info]
            parser["telnet"] = {"request_url": "http://10.0.0.1"}
            with config_path.open("w", encoding="utf-8") as file:
                parser.write(file)

            loaded = TestItemConfigStore(config_path).load()
            self.assertEqual(loaded.project_info.project_name, "")
            self.assertEqual(loaded.project_info.software_version, "")
            self.assertEqual(loaded.project_info.internal_software_version, "")
            self.assertEqual(loaded.project_info.onu_compile_time, "")


if __name__ == "__main__":
    unittest.main()
