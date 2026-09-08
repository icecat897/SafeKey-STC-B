#include "STC15F2K60S2.H"
#include "sys.H"
#include "displayer.H"
#include "Key.H"
#include "Beep.H"
#include "Uart1.H"

/* SafeKey 第一版：单片机作为本地文件保险箱的硬件认证器。
 * 串口固定 8 字节协议：主机发送 SKHLLO，单片机回复 SKRDY；
 * PIN 正确回复 SKOK，失败回复 SKER，三次失败回复 SKLK；每秒发送 SKALIVE。
 * 这是课程原型，后续可升级为挑战-响应摘要，避免固定结果被重放。
 */
code unsigned long SysClock = 11059200;

/* 硬件验证前请把此处改成自己的 6 位 PIN。 */
#define PIN_CODE "123456"
#define PIN_LEN 6
#define MAX_FAIL 3

code char decode_table[] = {
    0x3f,0x06,0x5b,0x4f,0x66,0x6d,0x7d,0x07,0x7f,0x6f,
    0x00,0x08,0x40,0x01,0x41,0x48,
    0x3f|0x80,0x06|0x80,0x5b|0x80,0x4f|0x80,
    0x66|0x80,0x6d|0x80,0x7d|0x80,0x07|0x80,
    0x7f|0x80,0x6f|0x80
};

unsigned char rx_buf[8], tx_buf[8], pin_buf[PIN_LEN];
unsigned char pin_pos, current_digit, fail_count, locked, online;
unsigned int lock_ticks;

void send_frame(char a,char b,char c,char d,char e,char f,char g,char h)
{
    tx_buf[0]=a; tx_buf[1]=b; tx_buf[2]=c; tx_buf[3]=d;
    tx_buf[4]=e; tx_buf[5]=f; tx_buf[6]=g; tx_buf[7]=h;
    Uart1Print(tx_buf,8);
}

void arm_rx(void) { SetUart1Rxd(rx_buf,8,0,0); }

void show_wait(void)
{
    unsigned char d0=10,d1=10,d2=10,d3=10,d4=10,d5=10;
    if(pin_pos>0) d0=pin_buf[0];
    if(pin_pos>1) d1=pin_buf[1];
    if(pin_pos>2) d2=pin_buf[2];
    if(pin_pos>3) d3=pin_buf[3];
    if(pin_pos>4) d4=pin_buf[4];
    if(pin_pos>5) d5=pin_buf[5];
    /* 当前正在编辑的数字实时显示在当前位置，主机端仍不会记录它。 */
    if(pin_pos==0) d0=current_digit;
    else if(pin_pos==1) d1=current_digit;
    else if(pin_pos==2) d2=current_digit;
    else if(pin_pos==3) d3=current_digit;
    else if(pin_pos==4) d4=current_digit;
    else if(pin_pos==5) d5=current_digit;
    Seg7Print(d0,d1,d2,d3,d4,d5,pin_pos,current_digit);
}

void clear_pin(void)
{
    unsigned char i;
    for(i=0;i<PIN_LEN;i++) pin_buf[i]=0;
    pin_pos=0; current_digit=0; show_wait();
}

unsigned char pin_matches(void)
{
    unsigned char i;
    for(i=0;i<PIN_LEN;i++)
        if(pin_buf[i]!=(unsigned char)(PIN_CODE[i]-'0')) return 0;
    return 1;
}

void auth_success(void)
{
    locked=0; fail_count=0; LedPrint(0xFF);
    Seg7Print(10,10,10,10,10,10,0,0);
    SetBeep(1800,120); send_frame('S','K','O','K',0,0,0,0);
}

void auth_failure(void)
{
    fail_count++; LedPrint(0x00);
    Seg7Print(10,10,10,10,10,10,9,fail_count);
    SetBeep(500,220); send_frame('S','K','E','R',fail_count,0,0,0);
    if(fail_count>=MAX_FAIL) {
        locked=1; lock_ticks=3000; LedPrint(0x81);
        send_frame('S','K','L','K',30,0,0,0);
    }
}

void handle_uart(void)
{
    if(rx_buf[0]=='S' && rx_buf[1]=='K' &&
       rx_buf[2]=='H' && rx_buf[3]=='L') {
        online=1; locked=0; fail_count=0; LedPrint(0x18);
        clear_pin(); send_frame('S','K','R','D','Y',0,0,0);
    }
    arm_rx();
}

void mykey(void)
{
    /* 标准 BSP 的按键状态只能在 enumEventKey 回调中读取。 */
    if(locked) return;
    online=1;
    if(GetKeyAct(enumKey1)==enumKeyPress) {
        current_digit++; if(current_digit>9) current_digit=0;
        Seg7Print(12,12,12,12,12,12,pin_pos,10);
        send_frame('S','K','K','Y',pin_pos,0,0,0);
        SetBeep(1200,30);
    }
    if(GetKeyAct(enumKey2)==enumKeyPress) {
        pin_buf[pin_pos]=current_digit; pin_pos++; current_digit=0;
        SetBeep(1400,30);
        send_frame('S','K','K','Y',pin_pos,0,1,0);
        if(pin_pos>=PIN_LEN) {
            if(pin_matches()) auth_success();
            else { auth_failure(); clear_pin(); }
        } else show_wait();
    }
    if(GetKeyAct(enumKey3)==enumKeyPress) {
        /* K3 回退到上一位；在第 0 位时只把当前数字归零。 */
        if(pin_pos>0) {
            pin_pos--;
            current_digit=pin_buf[pin_pos];
            pin_buf[pin_pos]=0;
        } else {
            current_digit=0;
        }
        show_wait(); SetBeep(800,50); send_frame('S','K','B','K',pin_pos,0,0,0);
    }
}

void my10ms(void)
{
    if(locked && lock_ticks>0) {
        lock_ticks--; 
        if(lock_ticks==0) { locked=0; fail_count=0; LedPrint(0x18); clear_pin(); }
    }
}

void my1s(void) { if(online) send_frame('S','K','A','L','I','V','E',0); }

void main(void)
{
    DisplayerInit(); SetDisplayerArea(0,7); KeyInit(); BeepInit();
    Uart1Init(2400); online=1; LedPrint(0x18); show_wait(); arm_rx();
    SetEventCallBack(enumEventSys10mS,my10ms);
    SetEventCallBack(enumEventKey,mykey);
    SetEventCallBack(enumEventSys1S,my1s);
    SetEventCallBack(enumEventUart1Rxd,handle_uart);
    MySTC_Init(); while(1) MySTC_OS();
}
