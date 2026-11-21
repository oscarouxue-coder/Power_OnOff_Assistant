# GUI测试闪窗修复与覆盖门禁

负责人已确认实施：覆盖完整基线、命令行全量/单项、VS Code任务及GUI测试子进程；支持入口统一先预检，新增真实GUI测试漏接入即失败。

- 静态AST检查测试及辅助模块的Tk/Toplevel、别名、Tk子类、继承夹具、安装顺序、作用域和内联子进程；不能确认的已识别入口失败，不靠人工刷新通过名单。
- 统一入口在导入测试之前安装严格运行时守卫，捕获动态构造、错误线程、原生对话框和作用域泄漏；异常被捕获仍保留非零退出码。纯Mock/Tcl保留。
- 公共离屏工具保持原接口，补齐重复安装、嵌套所有权、父子相对定位、异常清理；现有真实GUI测试接入。子进程使用有超时、独立报告且失败关闭的包装入口。
- 完整基线新增第八类覆盖门禁、通过统一入口运行unittest，保留计数/测试ID/原门禁；失败不启动GUI测试。VS Code提供全量和指定ID任务。
- 反向验证漏接、晚接、条件接入、动态调用、错误线程、捕获异常、子进程缺证据/失败、伪造隔离身份及泄漏；正向验证真实布局/映射、主题、窗口重开及原生像素。

## 实施中验证后的适配

原通道列表像素检查的GetDC/GetPixel在桌面外返回无效像素，PrintWindow也不能提供等价结果。因此仅该原生像素专项使用一次性Windows私有桌面：父进程CreateDesktopW；子进程在导入Tk前OpenDesktopW/SetThreadDesktop；守卫通过GetThreadDesktop/OpenInputDesktop/GetUserObjectInformationW核验不同于输入桌面。不调用SwitchDesktop，结束后父进程关闭桌面句柄。保留原GetPixel、焦点、Vista/Clam六组颜色断言，隔离不可用时失败，不跳过或回退。

CPython subprocess没有传递任意STARTUPINFO.lpDesktop属性，因此不能依赖该属性；身份检查曾拦截此无效启动方式，现使用显式子线程桌面绑定。

只修改测试设施与文档，不改产品行为、不触碰build/dist/logs/.venv，不操作设备、不提交/发布。按相关检查验证；完整基线继续遵守原触发条件。结果见DEVELOPMENT_LOG本轮条目。
