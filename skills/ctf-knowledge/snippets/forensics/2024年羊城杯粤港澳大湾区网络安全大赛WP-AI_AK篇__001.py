# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/2024年羊城杯粤港澳大湾区网络安全大赛WP-AI_AK篇.md
# TITLE: 2024年羊城杯粤港澳大湾区网络安全大赛WP-AI AK篇
# CATEGORY: forensics

def verify_similarity(original, modified, model, tokenizer):
    # 确保模型处于评估模式
    model.eval()

    # 对原始文本和修改后的文本进行编码
    original_encoding = tokenizer(original, return_tensors='pt', padding=True, truncation=True, max_length=512)
    modified_encoding = tokenizer(modified, return_tensors='pt', padding=True, truncation=True, max_length=512)

    with torch.no_grad():
        # 获取原始文本的隐藏状态
        original_outputs = model.distilbert(**original_encoding)
        original_hidden_state = original_outputs.last_hidden_state.mean(dim=1)

        # 获取修改后文本的隐藏状态
        modified_outputs = model.distilbert(**modified_encoding)
        modified_hidden_state = modified_outputs.last_hidden_state.mean(dim=1)

    # 计算余弦相似度
    similarity = cosine_similarity(original_hidden_state.cpu().numpy(),
                                modified_hidden_state.cpu().numpy())[0][0]

    return similarity
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import torch
from sklearn.metrics.pairwise import cosine_similarity
import csv
# sentiment-analysis 默认使用的 checkpoint
checkpoint = "./Sentiment_classification_model"

# 建立 tokenizer，加载模型的 checkpoint，建立 model 对象实例
tokenizer = AutoTokenizer.from_pretrained(checkpoint)
model = AutoModelForSequenceClassification.from_pretrained(checkpoint)
def verify_similarity(original, modified, model, tokenizer):
    # 确保模型处于评估模式
    model.eval()

    # 对原始文本和修改后的文本进行编码
    original_encoding = tokenizer(original, return_tensors='pt', padding=True, truncation=True, max_length=512)
    modified_encoding = tokenizer(modified, return_tensors='pt', padding=True, truncation=True, max_length=512)

    with torch.no_grad():
        # 获取原始文本的隐藏状态
        original_outputs = model.distilbert(**original_encoding)
        original_hidden_state = original_outputs.last_hidden_state.mean(dim=1)

        # 获取修改后文本的隐藏状态
        modified_outputs = model.distilbert(**modified_encoding)
        modified_hidden_state = modified_outputs.last_hidden_state.mean(dim=1)

    # 计算余弦相似度
    similarity = cosine_similarity(original_hidden_state.cpu().numpy(),
                                modified_hidden_state.cpu().numpy())[0][0]
    if similarity < 0.7:
        return False
    else:
        return True
    # return similarity
def predict_model(tokenizer,model,raw_inputs):
    # 原始输入序列
    # raw_inputs = ["Good mornin. Today will end early, woo. Gonna work on rick`s surprise PROJECT DUE ON TUESDAY"]
    
    # 调用 Tokenizer 进行预处理，预处理的结果会作为 Model 的输入
    inputs = tokenizer(raw_inputs, padding=True, truncation=True, return_tensors="pt")
    # encoded_input = tokenizer(sentence, return_tensors='pt')
    
    
    # 将 Tokenizer 预处理后的数据传送给 Model，“**”用于将 inputs 字典中的键值对解包成模型的输入参数
    outputs = model(**inputs)
    
    # 打印一下 Transformer 输出的 Logits 的结构信息
    # print(outputs.logits.shape)
    
    # 打印一下 Transformer 输出的 Logits 的信息
    # print(outputs.logits)
    predictions = outputs.logits
    
    # 解析预测结果
    # 假设模型有两个类别：0 表示负面，1 表示正面
    # if predictions.argmax() == 0:
    #     print("该句子情感为负面")
    # elif predictions.argmax() == 1:
    #     print("该句子情感为无所谓")
    # elif predictions.argmax() == 2:
    #     print("该句子情感为正面")
    # return str(predictions.argmax())
    return str(int(predictions.argmax()))
 
 
filename = 'original_text.csv'
data_dict = {}
with open(filename, newline='') as csvfile:
    csvreader = csv.reader(csvfile)
    for row in csvreader:
        if row[0] == "id":
            continue
        data_dict[row[0]] = {'text':
row[1],'label':
row[3]}
        
data_dict_2 = {}
for id in data_dict:
    original_text = data_dict[id]['text']
    label = data_dict[id]['label']
    if label == "0": #neg
        data_dict_2[id] = {"text":"happy " + original_text}
    elif label == "2":
        data_dict_2[id] = {"text":"nothing " + original_text}
    elif label == "1": #pos
        data_dict_2[id] = {"text":"unhappy " + original_text}

def calc_accuracy(data_dict,new_data_dict):
    value = 0
    for id in data_dict:
        original_text = data_dict[id]['text']
        modified_text = new_data_dict[id]['text']
        result = predict_model(tokenizer,model,modified_text)
        label = data_dict[id]['label']
        if result != label:
            if verify_similarity(original_text, modified_text, model, tokenizer):
                value += 1
        else:
            pass
    print(f"{value/len(data_dict) * 100}%")

calc_accuracy(data_dict,data_dict_2)
pre_failed 1 2 nothing Good mornin. Today will end early, woo. Gonna work on rick`s surprise PROJECT DUE ON TUESDAY
pre_failed 2 0 happy  im only on 1800  lol
pre_failed 3 2 nothing was busy talking with mom and bhabhi.. they liked the cards bro and me made for them  now waiting for sis to get back from Church..
pre_failed 11 0 happy  Nothing definite yet..and the show is in a week   I may just be resorted to giving them away
pre_failed 13 0 happy forgot my macbook`s recharger, that means nothing but Pratchett for me today
pre_failed 16 2 nothing  Stress test: http://www.selfhelpmagazine.com/psychtoons/glasbergen/StressManagement/StressTest.gif  Good luck!
pre_failed 20 0 happy _G  ur a poopy head
pre_failed 21 2 nothing  aww you poor thing  hope all goes well!
pre_failed 24 0 happy http://www.myspace.com/dica_grl Just got a crush on this song! Disco`s Out! Murder`s In! ruleaz?, zic!  www.myspace.com/discosoutmurdersin
pre_failed 28 0 happy 2nd to last episode of jay leno  itll never be the same!  nite twitter
pre_failed 36 2 nothing Nice PC Authority review of the Tivo VOD service here: http://bit.ly/Ps7y2  I`m still loving my Tivo
pre_failed 37 2 nothing - It`s time for Kathleen to go to bed... waaaaay past time. Don`t expect to hear from me before noon. lol  Have a BLESSED morning.
pre_failed 38 2 nothing Am good thanks, what`s Miami saying? How come u wrote to me?
pre_failed 43 0 happy I wanna go to the beach...but I have to study
pre_failed 48 0 happy  Don`t leave forever! We`ll miss you too much
pre_failed 50 2 nothing  bugger, that would have been nice but typically, we`re heading to Bristol
pre_failed 51 0 happy _0 have you considered cordoning off a corner of the park with beware 'Swine flu' signs might clear it out for you
pre_failed 58 2 nothing Had a nice pre mother`s day dinner out. Now a cocktail before retiring for the evening
ver_failed 59 0 happy   well hit me and we can see...it depends then
pre_failed 66 2 nothing Last Late Late with Pat Kenny! Bless
pre_failed 67 1 unhappy Checked if there`s a new comment on friendster!
pre_failed 76 2 nothing  hahaha wow thanks bud :p but my plan is to pretend its a costume... I wish it were cold so i could wear a sweatshirt over this
pre_failed 79 0 happy off to go buy more deck sleeves and 3X3 card pages.  Man, those pages are expensive!   Stupid organizing collection.
pre_failed 82 0 happy It`s 6 am, I haven`t been to bed yet, and I just got my second wind.  Guess I should edit or read or something until I feel tired huh?
pre_failed 84 2 nothing  no way - those are great words.  Boys don`t get to own them.    Oh and was it your bday?
pre_failed 91 1 unhappy Heyya guys! does anyone know how to give formulas to create a sudoku? Please help
pre_failed 93 2 nothing  y r we giving up on people?  I actually thought that way for a while too before I found someone who is very intriguing
pre_failed 95 2 nothing  Oh! Don`t you just love these Vodafone series of Ads ... The best picturisation ever
pre_failed 96 0 happy  or so a month. I put my 2 week`s notice in a little over a week ago, my last day is this friday!
pre_failed 97 0 happy recorded some of a new song today! u wont hear it for a long time thooo... we might play it at shows tho! so comeeeeee
pre_failed 98 2 nothing Heading home after a long week. Wish someone onther than marketers would follow me
data_dict_2 = {}
for id in data_dict:
    original_text = data_dict[id]['text']
    label = data_dict[id]['label']
    if label == "0": #neg
        data_dict_2[id] = {"text":"happy " + original_text}
    elif label == "2":
        data_dict_2[id] = {"text":"nothing " + original_text}
    elif label == "1": #pos
        data_dict_2[id] = {"text":"unhappy " + original_text}
    if id in ["1","2","3","11","13","16","20","21","24","28","36","37","38","43","48","50","51","58","59","66","67","76","79","82","84","91","93","95","96","97","98"]:
        data_dict_2[id] = {"text":"very " + data_dict_2[id]['text']}
calc_accuracy(data_dict,data_dict_2)
pre_failed 1 2 very nothing Good mornin. Today will end early, woo. Gonna work on rick`s surprise PROJECT DUE ON TUESDAY
ver_failed 2 0 very happy im only on 1800 lol
pre_failed 3 2 very nothing was busy talking with mom and bhabhi.. they liked the cards bro and me made for them now waiting for sis to get back from Church..
pre_failed 11 0 very happy Nothing definite yet..and the show is in a week I may just be resorted to giving them away
pre_failed 16 2 very nothing Stress test: http://www.selfhelpmagazine.com/psychtoons/glasbergen/StressManagement/StressTest.gif Good luck!
ver_failed 20 0 very happy _G ur a poopy head
pre_failed 21 2 very nothing aww you poor thing hope all goes well!
pre_failed 36 2 very nothing Nice PC Authority review of the Tivo VOD service here: http://bit.ly/Ps7y2 I`m still loving my Tivo
pre_failed 37 2 very nothing - It`s time for Kathleen to go to bed... waaaaay past time. Don`t expect to hear from me before noon. lol Have a BLESSED morning.
pre_failed 38 2 very nothing Am good thanks, what`s Miami saying? How come u wrote to me?
pre_failed 50 2 very nothing bugger, that would have been nice but typically, we`re heading to Bristol
pre_failed 58 2 very nothing Had a nice pre mother`s day dinner out. Now a cocktail before retiring for the evening
ver_failed 59 0 very happy well hit me and we can see...it depends then
pre_failed 66 2 very nothing Last Late Late with Pat Kenny! Bless
pre_failed 76 2 very nothing hahaha wow thanks bud :p but my plan is to pretend its a costume... I wish it were cold so i could wear a sweatshirt over this
pre_failed 79 0 very happy off to go buy more deck sleeves and 3X3 card pages. Man, those pages are expensive! Stupid organizing collection.
pre_failed 84 2 very nothing no way - those are great words. Boys don`t get to own them. Oh and was it your bday?
pre_failed 93 2 very nothing y r we giving up on people? I actually thought that way for a while too before I found someone who is very intriguing
pre_failed 95 2 very nothing Oh! Don`t you just love these Vodafone series of Ads ... The best picturisation ever
pre_failed 96 0 very happy or so a month. I put my 2 week`s notice in a little over a week ago, my last day is this friday!
pre_failed 98 2 very nothing Heading home after a long week. Wish someone onther than marketers would follow me
79.0%
target_mapping = {
    0: 1,  # 原标签: cat -> 目标标签: dog
    1: 2,  # 原标签: dog -> 目标标签: fox
    2: 0   # 原标签: fox -> 目标标签: cat
}
model = models.densenet121(pretrained=True)
num_ftrs = model.classifier.in_features
model.classifier = nn.Sequential(
    nn.Linear(num_ftrs, 500),
    nn.Linear(500, 3) 
)

model.load_state_dict(torch.load(PATH, map_location=device))
model = model.to(device)
adv_image
 |____cat
 | |______cat_000.jpg
 | |______cat_001.jpg
 |____dog
 | |______dog_000.jpg
 | |______dog_001.jpg
 |____fox
 | |______fox_000.jpg
 | |______fox_001.jpg
tar -zcf xxxxx.tar.gz update
xxxx.tar.gz
|____update
 |____cat
 |______**.jpg
 |____dog
 |______**.jpg
 |____fox
 |______**.jpg
import torch
import torch.nn as nn
import torchvision.models as models
import torchvision as tv
import torchvision.transforms as transforms

import io
import matplotlib.pyplot as plt

from PIL import Image
from PIL import Image
import random

import pytorch_ssim
import torch
from torch.autograd import Variable
import cv2
import numpy as np

from torchvision.transforms import GaussianBlur
from torchvision.transforms import ToPILImage
from tqdm import tqdm

model = models.densenet121(pretrained=True)
num_ftrs = model.classifier.in_features
model.classifier = nn.Sequential(
    nn.Linear(num_ftrs, 500),
    nn.Linear(500, 3) 
)

device = torch.device("cpu")

model.load_state_dict(torch.load("./ckpt_densenet121_catdogfox_classify.pth", map_location=device))
model = model.to(device)
model.eval()

def transform_image(image_bytes):
    # my_transforms = transforms.Compose([transforms.Resize((224, 224)),  # DenseNet需要224x224的图片
    #                                     # 将PIL图片或NumPy ndarray转换为tensor，并归一化
    #                                     transforms.ToTensor(),
    #                                     # 归一化到[-1, 1]范围，使用ImageNet的均值和标准差
    #                                     transforms.Normalize(mean=[0.6377, 0.4879, 0.4189],
    #                                                      std=[0.2119, 0.1905, 0.1831]), ])
    my_transforms = transforms.Compose([transforms.ToTensor()])
    image = Image.open(io.BytesIO(image_bytes))
    return my_transforms(image).unsqueeze(0)

def judge_pic(img_path):
    with open(img_path, 'rb') as f:
        image_bytes = f.read()
    tensor = transform_image(image_bytes=image_bytes)
    tensor = tensor.to(device)
    outputs = model.forward(tensor)
    _, y_hat = outputs.max(1)
    return int(y_hat)

def ssim_pic(old,new):

    npImg1 = cv2.imread(old)
    img1 = torch.from_numpy(np.rollaxis(npImg1, 2)).float().unsqueeze(0)/255.0
    
    npImg2 = cv2.imread(new)
    img2 = torch.from_numpy(np.rollaxis(npImg2, 2)).float().unsqueeze(0)/255.0
    result = pytorch_ssim.ssim(img1, img2)
    return result
    # ssim_loss = pytorch_ssim.SSIM(window_size = 11)
    
    # print(ssim_loss(img1, img2))
def make_fooling_image(X, target_y, model,learning_rate,ori_pic,new_pic):
    # Initialize our fooling image to the input image, and wrap it in a Variable.
    X_fooling = X.clone()
    X_fooling_var = Variable(X_fooling, requires_grad=True)

    # learning_rate = 0.1
    for i in range(100):
        # forword
        scores = model(X_fooling_var)
        # Current max index.
        _, index = scores.data.max(dim=1)
        # print(index)
        # fool then break
        if index[0] == target_y:
            # dog组从X_fooling_var转图片后准确率下降，更改判定的方式
            K = X_fooling.clone()
            toPIL = transforms.ToPILImage()
            img = K.squeeze(0)
            pic = toPIL(img)
            pic.save(new_pic)
            with open(new_pic, 'rb') as f:
                image_bytes = f.read()
            tensor = transform_image(image_bytes=image_bytes)
            tensor = tensor.to(device)
            outputs = model.forward(tensor)
            _, y_hat = outputs.max(1)
            if int(y_hat) == target_y and (ssim_pic(ori_pic,new_pic))>=0.95:
                break
            else:
                pass
            # print(pytorch_ssim.ssim(X, X_fooling_var))
        # Score for the target class.
        target_score = scores[0,target_y]
        # Backward.
        target_score.backward()
        # Gradient for image.
        im_grad = X_fooling_var.grad.data
        # update pic
        X_fooling_var.data += learning_rate * (im_grad / im_grad.norm()) 
        # clear grad.
        X_fooling_var.grad.data.zero_()

    return X_fooling

def fool_gan_pic(ori_pic,new_pic,target,learning_rate):
    for g in range(5):
        with open(ori_pic, 'rb') as f:
            image_bytes = f.read()
        tensor = transform_image(image_bytes=image_bytes)
        tensor = tensor.to(device)
        change_x = make_fooling_image(tensor, target, model,learning_rate,ori_pic,new_pic)
        
        # result = pytorch_ssim.ssim(tensor, change_x)
        toPIL = transforms.ToPILImage()
        pic = toPIL(change_x[0])
        pic.save(new_pic)

        # image=Image.open(new_pic)
        # gauss=GaussianBlur(kernel_size=(5,9),sigma=(0.1,5))
        # iam=gauss(image)
        # iam.save(new_pic)
        
        if float(ssim_pic(ori_pic,new_pic)) < 0.95:
            # print("ssim too low")
            continue
        result = judge_pic(new_pic)
        # print(result)
        if result == target:
            # print(result)
            return True
    # print(ori_pic+" : failed!")
    return False

cat_file_list = []
for i in range(0,50):
    file_addr = './adv_image/cat/cat_0' + str(i).rjust(2,"0")+'.jpg'
    new_pic = file_addr.replace("adv_image/cat","adv_image/cat_new")
    cat_file_list.append([file_addr,new_pic])

dog_file_list = []
for i in range(0,50):
    file_addr = './adv_image/dog/dog_0' + str(i).rjust(2,"0")+'.jpg'
    new_pic = file_addr.replace("adv_image/dog","adv_image/dog_new")
    dog_file_list.append([file_addr,new_pic])

fox_file_list = []
for i in range(0,50):
    file_addr = './adv_image/fox/fox_0' + str(i).rjust(2,"0")+'.jpg'
    new_pic = file_addr.replace("adv_image/fox","adv_image/fox_new")
    fox_file_list.append([file_addr,new_pic])

learning_rate = 0.1
for target,file_list in [(1,cat_file_list),(2,dog_file_list),(0,fox_file_list)]:
    for i in range(0,50):
        ori_pic,new_pic = file_list[i]
        # model.load_state_dict(torch.load("./ckpt_densenet121_catdogfox_classify.pth", map_location=device))
        # model = model.to(device)
        # model.eval()
        if fool_gan_pic(ori_pic,new_pic,target,learning_rate):
            print("success : "+ori_pic)
        else:
            print("failed : "+ori_pic)

# success : ./adv_image/cat/cat_000.jpg
# success : ./adv_image/cat/cat_001.jpg
# success : ./adv_image/cat/cat_002.jpg
# success : ./adv_image/cat/cat_003.jpg
# success : ./adv_image/cat/cat_004.jpg
# success : ./adv_image/cat/cat_005.jpg
# success : ./adv_image/cat/cat_006.jpg
# success : ./adv_image/cat/cat_007.jpg
# success : ./adv_image/cat/cat_008.jpg
# failed : ./adv_image/cat/cat_009.jpg
# success : ./adv_image/cat/cat_010.jpg
# success : ./adv_image/cat/cat_011.jpg
# success : ./adv_image/cat/cat_012.jpg
# success : ./adv_image/cat/cat_013.jpg
# success : ./adv_image/cat/cat_014.jpg
# success : ./adv_image/cat/cat_015.jpg
# success : ./adv_image/cat/cat_016.jpg
# success : ./adv_image/cat/cat_017.jpg
# success : ./adv_image/cat/cat_018.jpg
# success : ./adv_image/cat/cat_019.jpg
# success : ./adv_image/cat/cat_020.jpg
# success : ./adv_image/cat/cat_021.jpg
# success : ./adv_image/cat/cat_022.jpg
# success : ./adv_image/cat/cat_023.jpg
# success : ./adv_image/cat/cat_024.jpg
# success : ./adv_image/cat/cat_025.jpg
# success : ./adv_image/cat/cat_026.jpg
# success : ./adv_image/cat/cat_027.jpg
# success : ./adv_image/cat/cat_028.jpg
# success : ./adv_image/cat/cat_029.jpg
# success : ./adv_image/cat/cat_030.jpg
# success : ./adv_image/cat/cat_031.jpg
# success : ./adv_image/cat/cat_032.jpg
# success : ./adv_image/cat/cat_033.jpg
# success : ./adv_image/cat/cat_034.jpg
# success : ./adv_image/cat/cat_035.jpg
# success : ./adv_image/cat/cat_036.jpg
# success : ./adv_image/cat/cat_037.jpg
# success : ./adv_image/cat/cat_038.jpg
# success : ./adv_image/cat/cat_039.jpg
# success : ./adv_image/cat/cat_040.jpg
# success : ./adv_image/cat/cat_041.jpg
# success : ./adv_image/cat/cat_042.jpg
# success : ./adv_image/cat/cat_043.jpg
# failed : ./adv_image/cat/cat_044.jpg
# success : ./adv_image/cat/cat_045.jpg
# success : ./adv_image/cat/cat_046.jpg
# success : ./adv_image/cat/cat_047.jpg
# success : ./adv_image/cat/cat_048.jpg
# success : ./adv_image/cat/cat_049.jpg
# failed : ./adv_image/dog/dog_000.jpg
# success : ./adv_image/dog/dog_001.jpg
# success : ./adv_image/dog/dog_002.jpg
# failed : ./adv_image/dog/dog_003.jpg
# success : ./adv_image/dog/dog_004.jpg
# success : ./adv_image/dog/dog_005.jpg
# failed : ./adv_image/dog/dog_006.jpg
# success : ./adv_image/dog/dog_007.jpg
# success : ./adv_image/dog/dog_008.jpg
# success : ./adv_image/dog/dog_009.jpg
# failed : ./adv_image/dog/dog_010.jpg
# success : ./adv_image/dog/dog_011.jpg
# success : ./adv_image/dog/dog_012.jpg
# success : ./adv_image/dog/dog_013.jpg
# success : ./adv_image/dog/dog_014.jpg
# failed : ./adv_image/dog/dog_015.jpg
# success : ./adv_image/dog/dog_016.jpg
# success : ./adv_image/dog/dog_017.jpg
# success : ./adv_image/dog/dog_018.jpg
# success : ./adv_image/dog/dog_019.jpg
# success : ./adv_image/dog/dog_020.jpg
# failed : ./adv_image/dog/dog_021.jpg
# success : ./adv_image/dog/dog_022.jpg
# success : ./adv_image/dog/dog_023.jpg
# success : ./adv_image/dog/dog_024.jpg
# success : ./adv_image/dog/dog_025.jpg
# success : ./adv_image/dog/dog_026.jpg
# success : ./adv_image/dog/dog_027.jpg
# success : ./adv_image/dog/dog_028.jpg
# success : ./adv_image/dog/dog_029.jpg
# success : ./adv_image/dog/dog_030.jpg
# success : ./adv_image/dog/dog_031.jpg
# success : ./adv_image/dog/dog_032.jpg
# success : ./adv_image/dog/dog_033.jpg
# failed : ./adv_image/dog/dog_034.jpg
# success : ./adv_image/dog/dog_035.jpg
# success : ./adv_image/dog/dog_036.jpg
# success : ./adv_image/dog/dog_037.jpg
# success : ./adv_image/dog/dog_038.jpg
# success : ./adv_image/dog/dog_039.jpg
# success : ./adv_image/dog/dog_040.jpg
# success : ./adv_image/dog/dog_041.jpg
# failed : ./adv_image/dog/dog_042.jpg
# success : ./adv_image/dog/dog_043.jpg
# failed : ./adv_image/dog/dog_044.jpg
# success : ./adv_image/dog/dog_045.jpg
# success : ./adv_image/dog/dog_046.jpg
# success : ./adv_image/dog/dog_047.jpg
# failed : ./adv_image/dog/dog_048.jpg
# success : ./adv_image/dog/dog_049.jpg
# success : ./adv_image/fox/fox_000.jpg
# success : ./adv_image/fox/fox_001.jpg
# success : ./adv_image/fox/fox_002.jpg
# success : ./adv_image/fox/fox_003.jpg
# success : ./adv_image/fox/fox_004.jpg
# success : ./adv_image/fox/fox_005.jpg
# success : ./adv_image/fox/fox_006.jpg
# success : ./adv_image/fox/fox_007.jpg
# success : ./adv_image/fox/fox_008.jpg
# success : ./adv_image/fox/fox_009.jpg
# success : ./adv_image/fox/fox_010.jpg
# success : ./adv_image/fox/fox_011.jpg
# success : ./adv_image/fox/fox_012.jpg
# success : ./adv_image/fox/fox_013.jpg
# success : ./adv_image/fox/fox_014.jpg
# success : ./adv_image/fox/fox_015.jpg
# success : ./adv_image/fox/fox_016.jpg
# success : ./adv_image/fox/fox_017.jpg
# success : ./adv_image/fox/fox_018.jpg
# success : ./adv_image/fox/fox_019.jpg
# success : ./adv_image/fox/fox_020.jpg
# success : ./adv_image/fox/fox_021.jpg
# success : ./adv_image/fox/fox_022.jpg
# success : ./adv_image/fox/fox_023.jpg
# success : ./adv_image/fox/fox_024.jpg
# success : ./adv_image/fox/fox_025.jpg
# success : ./adv_image/fox/fox_026.jpg
# success : ./adv_image/fox/fox_027.jpg
# success : ./adv_image/fox/fox_028.jpg
# success : ./adv_image/fox/fox_029.jpg
# success : ./adv_image/fox/fox_030.jpg
# success : ./adv_image/fox/fox_031.jpg
# success : ./adv_image/fox/fox_032.jpg
# success : ./adv_image/fox/fox_033.jpg
# success : ./adv_image/fox/fox_034.jpg
# success : ./adv_image/fox/fox_035.jpg
# success : ./adv_image/fox/fox_036.jpg
# success : ./adv_image/fox/fox_037.jpg
# success : ./adv_image/fox/fox_038.jpg
# success : ./adv_image/fox/fox_039.jpg
# success : ./adv_image/fox/fox_040.jpg
# success : ./adv_image/fox/fox_041.jpg
# success : ./adv_image/fox/fox_042.jpg
# success : ./adv_image/fox/fox_043.jpg
# success : ./adv_image/fox/fox_044.jpg
# success : ./adv_image/fox/fox_045.jpg
# success : ./adv_image/fox/fox_046.jpg
# success : ./adv_image/fox/fox_047.jpg
# success : ./adv_image/fox/fox_048.jpg
# success : ./adv_image/fox/fox_049.jpg

def calc_accury():
    value = 0
    count = 0
    for target,file_list in [(1,cat_file_list),(2,dog_file_list),(0,fox_file_list)]:
        for i in range(0,50):
            ori_pic,new_pic = file_list[i]
            if target == judge_pic(new_pic) and float(ssim_pic(ori_pic,new_pic)) >= 0.95:
                value += 1
            else:
                pass
            count += 1
    print(f"{value/count * 100}%")
calc_accury() 

# 92%
