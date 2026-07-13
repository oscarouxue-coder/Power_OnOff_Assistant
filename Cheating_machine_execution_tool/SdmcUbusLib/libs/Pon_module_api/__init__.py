"""
应用相关api
"""
from urllib.parse import urlparse
from SdmcUbusLib.libs.Pon_module_api.pon_register import PonRegisterManager
from SdmcUbusLib.libs.base_moudle_api.ubus_lib_base import SdmcUbusLibBase
from SdmcLog import log
from SdmcCode import *
import inspect


class SdmcPonLib(object):
    """
    """

    def __init__(self):
        """
        """

        self._get_self_keywords()

    def _get_self_keywords(self):
        """
        """
        self.keywords = []

        # ✅ 自动发现：所有以 "MyLibrary_" 开头的方法
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("Ubus_"):
                # 转换成关键字名，比如 "MyLibrary_test" -> "MyLibrary test"
                self.keywords.append(name)

    def _Ubus_Pon_Register_init(self):
        ret = ERR_FAIL

        try:
            parsed_url = urlparse(SdmcUbusLibBase.Url)
            ip = parsed_url.hostname

            username = SdmcUbusLibBase.Username
            password = SdmcUbusLibBase.Password

            self.pon_register = PonRegisterManager(ip, username, password)

            ret = ERR_SUCCESS

        except Exception as e:
            log.exception(str(e))

        return ret

    def Ubus_get_authtype(self):
        """
        【功能描述】
            获取当前认证方式
        【入参】
            无
        【返回值】
            返回当前认证方式
        【示例】
        Example:
            [0, {'X_SDMC_AuthType': 'Password'}]
        """
        self._Ubus_Pon_Register_init()
        Pon_Register = self.pon_register
        authtype = Pon_Register.get_auth_type()

        return authtype

    def Ubus_get_sn_info(self):
        """
        【功能描述】
            获取当前sn
        【入参】
            无
        【返回值】
            返回当前sn
        【示例】
        Example:
           {'password_mode': 'hex', 'password': '31323333', 'sn': 'MING11112222'}
        """
        self._Ubus_Pon_Register_init()
        Pon_Register = self.pon_register
        sn_info = Pon_Register.get_sn_info()

        return sn_info

    def Ubus_get_loid_info(self):
        """
        【功能描述】
            获取当前loid 信息
        【入参】
            无
        【返回值】
            返回前loid 信息
        【示例】
        Example:
           {'loid': 'mtk1234', 'loid_password': '1234'}
        """
        self._Ubus_Pon_Register_init()
        Pon_Register = self.pon_register
        loid_info = Pon_Register.get_loid_info()

        return loid_info

    def Ubus_set_pon_register_info(self, authtype="Password", loid="mtk1234", loid_password="1234", password_mode="ascii", password="1234", sn="MMMM11112222"):
        """
        【功能描述】
            设置pon的注册信息
        【入参】
            authtype:str 注册方式 LOID或者Password
            loid:str loid 0-24位
            loid_password:str loid密码 0-12位
            password_mode:str 密码模式 hex或者ascii
            password:str 密码 hex 20位，ascii 10位
            sn:str sn 固定12位
        【返回值】

        【示例】
        Example:
            Ubus_set_pon_register_info("LOID", "mtk1234", "1234", "ascii", "1234", "MMMM11112222")
        """
        self._Ubus_Pon_Register_init()
        Pon_Register = self.pon_register
        Pon_Register.set_auth_type(authtype)
        if authtype == "LOID":
            Pon_Register.set_loid_info(loid, loid_password)
        else:
            Pon_Register.set_sn_info(password_mode, password, sn)

    def get_keyword_names(self):
        """
        """
        # 合并所有子库关键字
        names = self.keywords

        return names

    def run_keyword(self, name, args, kwargs=None):
        """
        """
        method_name = name
        if hasattr(self, method_name):
            return getattr(self, method_name)(*args, **kwargs)

    def get_keyword_documentation(self, name):
        """
        """
        method_name = name.replace(" ", "_")
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            doc = inspect.getdoc(method)
            return doc if doc else "No documentation provided."

    def get_keyword_arguments(self, name):
        """返回关键字的参数列表"""
        method_name = name
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            sig = inspect.signature(method)

            args = []
            for p in sig.parameters.values():
                if p.name == "self":
                    continue
                if p.kind == p.VAR_POSITIONAL:
                    args.append("*" + p.name)  # *args
                elif p.kind == p.VAR_KEYWORD:
                    args.append("**" + p.name)  # **kwargs
                elif p.default is inspect._empty:
                    args.append(p.name)  # 必填参数
                else:
                    args.append(f"{p.name}={p.default!r}")  # 带默认值的参数
            return args


if __name__ == '__main__':
    """
    """
    n_ret = 0
    n_ret_api = 0
    desc = u""

    # logging.getLogger().setLevel(logging.DEBUG)
    # logging.basicConfig(filename='example.log',level=logging.INFO)

    print("start ---------------------------\n")

    print("\nfinish ------------------")
    # os.system("pause")


