# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/看雪·众安_2021_KCTF_秋季赛_-_第四题设计思路及解析.md
# TITLE: 看雪·众安 2021 KCTF 秋季赛 | 第四题设计思路及解析
# CATEGORY: pwn

import string
from pwn import *def L_TRUE(): return "(\x \y x)" def L_FALSE(): return "(\x \y y)" def L_ZERO(): return "(\f \x x)" def L_SUCC(): return "(\n \f \x n f (f x))" def L_NUM(n): s = L_ZERO() for _ in range(n): s = "("+ L_SUCC() + " " + s + ")" return s def L_FLAG_NODE(i): return ("(z %d )" % i) def L_SUB(): return "(\m\n n " + L_PRE() + " m)" def L_PRE(): return "(\n\f\x " + L_CDR() + " (n (" + L_PREFN() + " f) (" + L_CONS() + " x x)))" def L_CDR(): return "(\p p " + L_FALSE() + ")" def L_CONS(): return "(\x \y \f f x y)" def L_PREFN(): return "(\f \p " + L_CONS() +" (f (" + L_CAR() + " p)) (" + L_CAR() + " p))" def L_CAR(): return "(\p p " + L_TRUE() + ")" def L_ADD(): return "(\m \n \f \x m f (n f x))" def L_IF(): return "(\p \x \y p x y)" def L_NOT(): return "(\p \a \b p b a)" def L_XOR(): # only works for boolean value return "(\a \b a (" + L_NOT() + " " + "b" + ") b)" def L_MULT(): return "(\m \n \f m (n f))" def H_ADD(l, r): return "(" + L_ADD() + " " + l + " " + r + ")" def H_MULT(l, r): return "(" + " ".join([L_MULT(), l , r]) + ")" def H_SUB(l, r): return "(" + " ".join([L_SUB(), l , r]) + ")" def H_XOR(l, r): return "(" + " ".join([L_XOR(), l , r]) + ")" def H_ABSDIFF(l, r): return H_ADD(H_SUB(l, r), H_SUB(r, l)) import random
def challenge(flag, seed): random.seed(seed) sub_eq = [] flag_seq = [] for c in bytes(flag): flag_seq.append(c & 0xf) flag_seq.append(c >> 0x4) s = L_NUM(0) for i in range(len(flag_seq)): l1 = random.randint(1, 10) d2 = random.randint(1, 10) target = flag_seq[i] * l1 + d2 print((l1, d2, target), ",") sub_eq.append(H_ABSDIFF(H_ADD(H_MULT(L_FLAG_NODE(i), L_NUM(l1)), L_NUM(d2)), L_NUM(target))) for exp_i in range(len(sub_eq)): s = H_ADD(s, sub_eq[exp_i]) return s #print()def compile_data(text): p = process(["lambda/lambda", 'xxxx']) p.sendline(text) return p.recvall().decode('utf-8') def data2array(name, data): return "char " + name +"[] = {" + ",".join([hex(c) for c in data.encode("ASCII")]) + ", 0x0};" def gen_text_arr(t): return ("char * arr[] = {" + ",".join(['"%s"' % x for x in t]) + "};").replace("\","\\") ts = [L_NUM(i) for i in range(16)]ts.append(challenge(b"pediy{Lambda6}", 2))rr = gen_text_arr(ts)open("lambda/text_chall.h", "w").write(rr)input("step2")l = []for i in range(16): r = open("tests/enc/data_" + str(i) + ".txt", "r").read() l.append(data2array("num_%d" % i, r))open("lambda/nums.h", "w").write("n".join(l))open("lambda/chall.h", "w").write(data2array("chall", open("tests/enc/data_16.txt", "r").read()))
data = [(1, 2, 2) ,(2, 6, 20) ,(3, 5, 20) ,(5, 10, 40) ,(4, 10, 26) ,(1, 10, 16) ,(3, 7, 34) ,(7, 9, 51) ,(6, 9, 63) ,(8, 9, 65) ,(5, 1, 56) ,(1, 6, 13) ,(8, 6, 102) ,(7, 7, 35) ,(9, 3, 12) ,(9, 3, 57) ,(4, 4, 56) ,(1, 3, 9) ,(6, 3, 15) ,(3, 9, 27) ,(9, 6, 42) ,(9, 9, 63) ,(3, 8, 11) ,(7, 9, 51) ,(6, 10, 46) ,(6, 6, 24) ,(8, 3, 107) ,(7, 8, 57) ,]flag_l = []flag = ''for d in data: flag_l.append((d[2] - d[1]) // d[0])for i in range(len(flag_l) // 2): flag += chr((flag_l[i * 2 + 1] << 4 )| flag_l[i * 2])print(flag)
// 名称可从 vptr 的 typeinfo 中看到struct term { int type union { char ch; term *other; } term *next; int idx;}
voidparse_dump_term(const struct term * t, FILE * stream){ const struct term * pterm = t; int nparen = 0;
 for (;;) switch (pterm->type) { case Tlam: { // CHANGE if (pterm->data.lam.var == 'z') { fprintf(stream, "[x%d]", pterm->idx); goto Close_paren; } fprintf(stream, "Lam (%c, ", pterm->data.lam.var); pterm = pterm->data.lam.body; nparen++; continue;
template<class Archive>void serialize(Archive& ar, term &t, const unsigned int version) { ar& t.type; switch (t.type) { case Tlam: ar& t.data.lam.var; ar& t.idx; if (t.data.lam.var != 'z') { ar& t.data.lam.body; } break; case Tapp: ar& t.data.app.left; ar& t.data.app.right; break; case Tvar: ar& t.data.var; break; }}
term* parse_term_in(std::
istream &in) { boost::
archive::
text_iarchive ar(in); term *ret = nullptr; ar >> ret; return ret;}
term* parse_term_s(const char* s) { std::
istringstream ss(s); return parse_term_in(ss);}
def _ADD(a, b): return a + b
def _MULT(a, b): return a * b
def _bind(f, a): return lambda b: f(a,b)
def ADD(a): return _bind(_ADD, a)def MULT(a): return _bind(_MULT, a)def INC(a): return a+1
from z3 import *x = IntVector('x', 28)s = Solver()
def _SUB(a, b): # 一定要加，不加无解 s.add(a>=b) return a - b
def SUB(a): return _bind(_SUB, a)
with open("ctf4.txt", "rt") as f: data = f.read()
def call(p): if p[0] == "P": p = p[3:] a, p = call(p) p = p[2:] b, p = call(p) p = p[1:] return a(b), p elif p[0] == "A": p = p[4:] a, p = call(p) p = p[1:] return ADD(a), p elif p[0] == "S": p = p[4:] a, p = call(p) p = p[1:] return SUB(a), p elif p[0] == "I": p = p[4:] a, p = call(p) p = p[1:] return INC(a), p elif p[0] == "M": p = p[5:] a, p = call(p) p = p[1:] return MULT(a), p elif p[0] == "x": p = p[1:] c = 0 while p[c]>='0' and p[c]<='9': c+=1 r = int(p[:c]) p = p[c:] return x[r], p else: c = 0 while p[c]>='0' and p[c]<='9': c+=1 r = int(p[:c]) p = p[c:] return r, p
rr, _ = call(data)s.add(rr==0)s.check()print(s.model())
