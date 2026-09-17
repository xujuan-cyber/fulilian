# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/看雪2022_KCTF_秋季赛_-_第二题设计思路及解析.md
# TITLE: 看雪2022 KCTF 秋季赛 | 第二题设计思路及解析
# CATEGORY: crypto

sbase = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'def baseConv(a): s = '' l = len(sbase) while(a > 0): s += sbase[a % l] a //= l return s
def calc(num, cnt): for x in range(1, cnt): if (num * x + 1) % (cnt - 1) == 0: n = (num * x + 1) // (cnt - 1) print(n, x, "+1", baseConv(n)) if (num * x - 1) % (cnt - 1) == 0: n = (num * x - 1) // (cnt - 1) print(n, x, "-1", baseConv(n))

这里取num=10**19，cnt=32，计算calc(10**19, 32)结果为：

3870967741935483871 12 +1 ZSxZerX4xb46129032258064516129 19 -1 jyvP7x12lI7
a*x -1 = x (mod n)b*y +1 = y (mod n)n = 10000000000000000000
(a-1)*x = 1 (mod n)(b-1)*y = n-1 (mod n)
BN_new_int_401630(&g_temp_1_40A988, 4);BN_lshift_4023A0(&g_temp2_40A9AC, &g_temp_1_40A988, 3);if ( count_r_40A9F8 > 0 && *&bn_const_40A9D0._data[g_temp2_40A9AC._data[0]] == g_temp2_40A9AC._data[0] ){ BN_add_401730(&g_temp_1_40A988, &g_temp_1_40A988, &g_temp2_40A9AC); v13 = BN_mod_int_402360(&g_temp_1_40A988, g_count_40A9F4); bn_const_40A9D0._data[g_temp_1_40A988._data[0]] += 4; BN_lshift_4023A0(&g_temp_1_40A988, &g_temp_1_40A988, v13); BN_sub_401820(&g_temp2_40A9AC, &g_temp_1_40A988, &g_temp2_40A9AC);
31*x = 1 (mod n)31*y = n-1 (mod n)
import gmpy2 t = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz' def int_2_64(n): out = '' while True: out += t[n%62] n /= 62 if n == 0: break return out def main(): n = 10000000000000000000 x = gmpy2.invert(31,n) for i in range(100): if (i*n-1) % 31 == 0: break y = (i*n-1) / 31 print int_2_64(x)+'-'+int_2_64(y) if __name__ == '__main__': main()
