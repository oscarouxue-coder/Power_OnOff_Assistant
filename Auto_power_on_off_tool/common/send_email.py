# 邮件
# 1.用python代码发送邮件 文本邮件
# 2.发送html邮件
# 3.发送附件和图片
# smtplib  smtp进行封装
import smtplib
# 发送邮件正文
from email.mime.text import MIMEText
# 发送头部
from email.header import Header
from threading import Thread


class SendEmail(Thread):
    def __init__(self, logger):
        super(SendEmail, self).__init__()
        self.logger = logger

    def send_email_without_attachments(self, error_code, recv_Email=[]):
        try:
            # 创建邮箱服务器  邮局  SMTP_SSL(邮箱链接地址，端口号)
            # 邮箱链接地址：smtp.xx.com  端口号:自己去查
            # 163邮箱  网易邮箱  qq邮箱
            con = smtplib.SMTP_SSL('smtp.exmail.qq.com', '465')
            # 登录邮箱 用户名和密码
            # 163邮箱  qq邮箱 设置一下 用户名是邮箱名  密码：授权密码  qq邮箱--设置--账号--POP3/SMTP服务开启
            con.login('Ray_wang@sdmctech.com', 'PNZyKToQPZ5k5dcq')
            # self.logger.info(con)
            # 发送者账号
            sender = 'Ray_wang@sdmctech.com'
            # 接受者账号
            # recevier = ['Ray_wang@sdmctech.com']
            recevier = recv_Email
            print(len(recevier))
            if len(recevier) == 0:
                recevier = ['Ray_wang@sdmctech.com']

            # 邮件的内容  _text文本内容 正文  _subtype 文件类型 plain 文本 txt html base64
            message = MIMEText(_text=error_code, _subtype='plain', _charset='utf-8')

            # 设置头部 设置标题
            message['Subject'] = Header('****开关机工具挂测信息****')
            # 发件人
            message['From'] = Header('wang<Ray_wang@sdmctech.com>')
            # 接受人 的信息
            message['To'] = Header('Ray_wang@sdmctech.com')
            # 发送邮件  由谁发送  邮局发送 con  发送邮件失败
            con.sendmail(sender, recevier, message.as_string())
            self.logger.info('发送邮件成功')
        except Exception as e:
            self.logger.error('无法发送邮件:{}'.format(e))
