"""全包升级 Boot 进入方式"""
BOOT_ENTRY_LOGIN = "账号密码登录"
BOOT_ENTRY_SDMC = "SDMC 指令进入"
BOOT_ENTRY_OPTIONS = (BOOT_ENTRY_LOGIN, BOOT_ENTRY_SDMC)


def normalize_boot_entry(value: str) -> str:
    return value if value in BOOT_ENTRY_OPTIONS else BOOT_ENTRY_LOGIN
