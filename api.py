import netmiko
from netmiko import ConnectHandler

mikrotik_router_1 = {
    'device_type': 'mikrotik_routeros',
    'host':   '91.221.246.23',
    'port' : 44446,          
    'username': 'ilia',
    'password': 'Fhb$Hf601+',
}

sshCli = ConnectHandler(**mikrotik_router_1)
print( sshCli.find_prompt() )