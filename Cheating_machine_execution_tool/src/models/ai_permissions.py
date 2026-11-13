"""对话操作权限；完全访问授权不可持久化。"""
ASK = "ask"
AUTO = "auto_review"
FULL = "full_access"
PERMISSION_LABELS = {ASK: "请求批准", AUTO: "帮我批准", FULL: "完全访问"}
PERMISSION_DESCRIPTIONS = {
    ASK: "固定只读查询直接执行；首次登录、通用命令、文件写入及临时设备修改逐项批准",
    AUTO: "普通操作独立AI审查后自动执行；危险、不明或审查失败须批准；禁止操作不执行",
    FULL: "操作员已授权当前会话完全访问；跳过独立审查，危险操作也自动执行；结果不明不自动重试",
}


def normalize_permission(value):
    return value if isinstance(value, str) and value in PERMISSION_LABELS else AUTO
