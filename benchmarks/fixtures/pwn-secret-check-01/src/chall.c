
#include <stdio.h>
#include <unistd.h>

void win(void) {
    puts("flag{pwn_static_secret}");
}

int main(void) {
    char buf[16];
    setvbuf(stdout, 0, 2, 0);
    write(1, "Input: ", 7);
    read(0, buf, 256);
    puts("nope");
    return 0;
}
