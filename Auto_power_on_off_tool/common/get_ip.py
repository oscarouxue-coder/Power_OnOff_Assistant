# import netifaces
#
# all_ip=[]
# def get_local_ip():
#
#     interfaces = netifaces.interfaces()
#     for interface in interfaces:
#         addresses = netifaces.ifaddresses(interface)
#         if netifaces.AF_INET in addresses:
#             ip = addresses[netifaces.AF_INET][0]['addr']
#             print(ip)
#             all_ip.append(ip)
#     return all_ip
#
#
# get_local_ip()
