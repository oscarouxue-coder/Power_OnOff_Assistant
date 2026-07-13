# SdmcUbusLib API 文档生成说明

本说明文件介绍如何使用 **PyDoctor** 自动生成 `SdmcUbusLib` 及其子模块的 API 文档。

---

## 1. 安装 PyDoctor

如果尚未安装 PyDoctor，可以使用 pip 安装：

```bash
pip install pydoctor
```


## 2.项目目录结构要求
示例结构：
```bash
SdmcUbusLib/
├─ libs/
│  ├─ base_moudle_api/
│  │  └─ __init__.py
│  ├─ Network_module_api/
│  │  ├─ Lan_moudle_api/
│  │  │  └─ __init__.py
│  │  ├─ Wan_moudle_api/
│  │  │  └─ __init__.py
│  │  └─ __init__.py
│  ├─ Wlan_moudle_api/
│  │  └─ __init__.py
│  ├─ Management_module_api/
│  │  └─ __init__.py
│  ├─ Performance_module_api/
│  │  └─ __init__.py
│  ├─ Security_module_api/
│  │  └─ __init__.py
│  ├─ IPTV_module_api/
│  │  └─ __init__.py
│  ├─ Pon_module_api/
│  │  └─ __init__.py
│  ├─ Stability_moudle_api/
│  │  └─ __init__.py
│  └─ Voice_moudle_api/
│     └─ __init__.py
├─ SdmcUbusLib.py
└─ __init__.py
```

说明：

每个模块目录必须包含 __init__.py，否则 PyDoctor 会跳过该目录。

libs 下包含各个子模块 API，PyDoctor 会递归扫描生成文档。

主类 SdmcUbusLib.py 位于项目根目录。

## 3.创建 PyDoctor 配置文件
在项目根目录SdmcRobot\plugin\SdmcUbusLib下创建 pydoctor.toml：
```bash
[tool.pydoctor]
project-name = "SdmcUbusLib API"
project-url = "https://example.com"
html-output = "docs/api"
add-package = ["."]

```
说明：

project-name：项目名称

project-url：项目主页 URL

html-output：生成 HTML 文档的目录

add-package：扫描的包，可用 . 表示当前目录并递归扫描子模块

## 4.生成 API 文档步骤
1. 打开终端，进入项目根目录

2. 执行命令：
```bash
pydoctor --config=pydoctor.toml

```
3. 文档生成完成后，HTML 文件会在 docs/api 目录下

## 5.查看生成的文档

打开浏览器，访问：
```bash
docs/api/index.html
```
文档内容包括：

    类 SdmcUbusLib 及其方法

    libs 下所有子模块 API

    函数 docstring、参数说明和返回值

    模块层级结构导航

## 6. 注意事项

1. 方法必须带 docstring

    PyDoctor 只生成带 docstring 的类和函数文档

2. 递归扫描子模块

    add-package = ["."] 会自动递归扫描整个项目目录

3. 清理旧文档

    重新生成文档前，建议删除 docs/api 目录

4. 组合方法显示

    主类通过组合调用子库方法时，PyDoctor 只能显示主类方法

    子库内部方法需各自 docstring 完整
