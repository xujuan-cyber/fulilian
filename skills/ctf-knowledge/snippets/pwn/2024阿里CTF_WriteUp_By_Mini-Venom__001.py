# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024阿里CTF_WriteUp_By_Mini-Venom.md
# TITLE: 2024阿里CTF  WriteUp By Mini-Venom
# CATEGORY: pwn

#malloc 0x20 &show(ptr)
n1[0] = 0   
n1[15] = 4
n1[0] = 0   
n1[15] = 4
__int64 sub_20F7()
{
  int i; // [rsp+8h] [rbp-118h]
  int v2; // [rsp+Ch] [rbp-114h]
  char v3[264]; // [rsp+10h] [rbp-110h] BYREF overflow
  unsigned __int64 v4; // [rsp+118h] [rbp-8h]
    #mid edit & stack overflow
n1[0] = 0   
n1[15] = 4
    #writen by flyyy
from pwn import *
from ctypes import *
import warnings
warnings.filterwarnings("ignore", category=BytesWarning)
import copy
flag = [0 for i in range(19)]
flag[0] = -1 # 数组从下标1开始，flag[0]不使用
flag[15] = 7
flag[18] = 4
import hashlib
import itertools
######################训练模型##############################################
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.svm import LinearSVC
from sklearn.metrics import accuracy_score, classification_report
