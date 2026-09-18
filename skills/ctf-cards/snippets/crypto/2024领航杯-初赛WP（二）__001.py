# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024“领航杯”-初赛WP（二）.md
# TITLE: 2024“领航杯”-初赛WP（二）
# CATEGORY: crypto

# -*- coding: utf-8 -*-from Crypto.Util.number import bytes_to_long
from secret import flagimport randomimport gmpy2 def genPrime():    while True:        p = random.getrandbits(512)        tp = random.getrandbits(20)        if gmpy2.is_prime(p**4 + tp):            return p**4 + tp, tp p, tp = genPrime()q, tq = genPrime()m = bytes_to_long(flag)e = 0x10001n = p*qc = pow(m, e, n)print("n = %s" % n)print("e = %s" % e)print("c = %s" % c)print("tp = %s" % tp)print("tq = %s" % tq)
import randomimport refrom datetime import datetime, timedelta#需引入constant.py文件import constant as const
class IdNumber(str):    def __init__(self, id_number):        super(IdNumber, self).__init__()        self.id = id_number        self.area_id = int(self.id[0:6])        self.birth_year = int(self.id[6:10])        self.birth_month = int(self.id[10:12])        self.birth_day = int(self.id[12:14])    def get_area_name(self):        """根据区域编号取出区域名称"""        return const.AREA_INFO[self.area_id]    def get_birthday(self):        """通过身份证号获取出生日期"""        return "{0}-{1}-{2}".format(self.birth_year, self.birth_month, self.birth_day)    def get_age(self):        """通过身份证号获取年龄"""        now = (datetime.now() + timedelta(days=1))        year, month, day = now.year, now.month, now.day        if year == self.birth_year:            return 0        else:            if self.birth_month > month or (self.birth_month == month and self.birth_day > day):                return year - self.birth_year - 1            else:                return year - self.birth_year    def get_sex(self):        """通过身份证号获取性别， 女生：0，男生：1"""        return int(self.id[16:17]) % 2    def get_check_digit(self):        """通过身份证号获取校验码"""        check_sum = 0        for i in range(0, 17):            check_sum += ((1 << (17 - i)) % 11) * int(self.id[i])        check_digit = (12 - (check_sum % 11)) % 11        return check_digit if check_digit < 10 else 'X'    @classmethod    def verify_id(cls, id_number):        """校验身份证是否正确"""        if re.match(const.ID_NUMBER_18_REGEX, id_number):            check_digit = cls(id_number).get_check_digit()            return str(check_digit) == id_number[-1]        else:            return bool(re.match(const.ID_NUMBER_15_REGEX, id_number))
def check():    with open('sfz.txt', 'r', encoding='utf-8') as file:        for line in file:            value = line.strip()            if  IdNumber.verify_
746869735f69735f7077645f6a37316e617332this_is_pwd_j71nas2
hex(773094245109)0xb4000202f5hex(244813267701)0x39000202f5
0x202f5 = 131829
hex(721554637612)0xa80002032c
hix = 0                                for c in 'test123456': hix += ord(c)       hex(hix)
# 0x2f5 hix = 0                                for c in 'test1234567': hix += ord(c)       hex(hix)                               # 0x32c
0x0202f5   ^
0x01????
