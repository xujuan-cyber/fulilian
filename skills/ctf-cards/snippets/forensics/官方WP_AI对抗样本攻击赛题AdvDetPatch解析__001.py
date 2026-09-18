# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/CTF大赛WP集合/articles/官方WP_-_AI对抗样本攻击赛题AdvDetPatch解析.md
# TITLE: 官方WP | AI对抗样本攻击赛题AdvDetPatch解析
# CATEGORY: forensics

def attack_loss(preds):
    """
    Computes the attack loss for object detection.

    Args:
        preds (List[Tensor[N, :]]): List of detection results.

    Returns:
        Tuple[float, int]: Tuple containing the object probability loss and the number of detected objects.
    """
    conf_thres = 0.25
    obj_prob_loss = 0
    objects_num = 0
    for i, pred in enumerate(preds):
        conf_mask = (pred[:, 4] >= conf_thres).squeeze()
        pred = pred[conf_mask]
        obj_prob_loss += (pred[:, 4].sum() / conf_mask.sum())
        objects_num = conf_mask.sum()
    return obj_prob_loss, objects_num
def create_patch_mask(detections=None, width=1, line_distance=50, shape=(640,640)):
    """
    Creates a mask over the image where detections are located, with lines drawn at regular intervals.

    Args:
        detections (List[[N, 4]]): List of detections returned by non-maximum suppression, (int).
        width (int): Width of the lines.
        line_distance (int): Distance between the lines.
        shape (Tuple[int, int]): Shape of the output mask.

    Returns:
        Tensor containing the binary mask of the patches.
    """
    mask = torch.zeros(*shape, 3)
    for _, (x1, y1, x2, y2) in enumerate(detections):
        x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        for i in range(1, 100):
            if mask.sum() > 20480*3: break
            if y1 + i*line_distance > y2: break
            tmp_mask = torch.zeros(*shape, 3)
            tmp_mask[np.clip(y1+i*line_distance, 0, shape[1]):np.clip(y1+i*line_distance+width, 0, shape[1]), x1:x2, :]=1
            mask = mask + tmp_mask
        for i in range(1,100):
            if mask.sum() > 20480*3: break
            if x1 + i*line_distance > x2: break
            tmp_mask = torch.zeros(*shape, 3)
            tmp_mask[y1:y2, np.clip(x1+i*line_distance, 0, shape[1]):np.clip(x1+i*line_distance+width, 0, shape[1]), :]=1
            mask = mask + tmp_mask
            
    mask = np.clip(mask,0,1)
    return mask
# initialize the patch
patch = torch.randn(input_tensor.shape).float() + 127/255  #大初始值加速收敛
patch = patch.to(input_tensor.device)
patch.requires_grad = True
# apply the patch to the image
patch_img = input_tensor * (1-mask) + patch * mask
patch_img = torch.clamp(patch_img,0,1)
patch_img = patch_img.to(device)
# attack
preds = model(patch_img, augment=opt.augment, visualize=opt.visualize)
attack_loss, obj_num = attack_loss(preds)
attack_loss.backward()
patch.data = patch - eps * patch.grad.sign()
ctf@engine-1:/home/adv$ ll
total 91476
drwxr-xr-x 1 root root 4096 May 29 07:49 ./
drwxr-xr-x 1 root root 4096 May 27 14:39 ../
drwxr-xr-x 1 ctf ctf 4096 May 27 14:38 adv_images/
-rwx------ 1 root root 42 May 29 07:49 flag*
-rwxr-xr-x 1 root root 5801 May 27 14:30 fool_me.py*
drwxr-xr-x 2 root root 4096 May 27 14:38 images/
drwxr-xr-x 2 root root 4096 May 27 14:38 models/
drwxr-xr-x 2 root root 4096 May 27 14:38 utils/
-rw-r--r-- 1 root root 93622629 May 24 16:04 yolov5l.pt
ctf@engine-1:~$ ln -s /home/adv/adv_images/ .
ctf@engine-1:~$ ls
README.md adv_images yolov5l.pt
ctf@engine-1:~$ ln -s /home/adv/ .
adv_images/ flag fool_me.py images/ models/ utils/ yolov5l.pt
ctf@engine-1:~$ ln -s /home/adv/images/ .
ctf@engine-1:~$ ln -s /home/adv/models/ .
ctf@engine-1:~$ ln -s /home/adv/utils/ .
ctf@engine-1:~$ ln -s /home/adv/f .
flag fool_me.py
ctf@engine-1:~$ ln -s /home/adv/flag .
ctf@engine-1:~$ sudo python3 /home/adv/fool_me.py
OpenBLAS WARNING - could not determine the L2 cache size on this system, assuming 256k
OpenBLAS WARNING - could not determine the L2 cache size on this system, assuming 256k
OpenBLAS WARNING - could not determine the L2 cache size on this system, assuming 256k
------------------Initializing detector-------------------
Fusing layers...
Model Summary: 213 layers, 1867405 parameters, 0 gradients
libpng warning: iCCP: known incorrect sRGB profile
libpng warning: iCCP: profile 'ICC Profile': 'RGB ': RGB color space not permitted on grayscale PNG
libpng warning: iCCP: known incorrect sRGB profile
libpng warning: iCCP: cHRM chunk does not match sRGB
---------------------Start detecting----------------------
[*]I see nothing!
[*]Give you the flag
flag{1998c094-64e4-4b06-99bb-d030a35660f3}
FileNotFoundError: [Errno 2] No such file or directory: 'yolov5l.pt'
import argparse
import cv2
import torch
import numpy as np
from models.common import DetectMultiBackend
from utils.datasets import LoadImages
from utils.general import non_max_suppression, check_patchsize
from utils.torch_utils import select_device, time_sync
import matplotlib.pyplot as plt
import matplotlib
import pickle
from PIL import Image

matplotlib.use('TkAgg')

# @torch.no_grad()
def run(weights='yolov5l.pt',  
        source='adv_images/stop.png',  # adversarial image path
        clean_path='images/stop.png',
        mask_path='adv_images/mask.png',
        imgsz=640,  # inference size (pixels)
        conf_thres=0.25,  # confidence threshold
        iou_thres=0.45,  # NMS IOU threshold
        max_det=1000,  # maximum detections per image
        device='cpu',  # cuda device, i.e. 0 or 0,1,2,3 or cpu
        classes=None,  # filter by class: --class 0, or --class 0 2 3
        agnostic_nms=False,  # class-agnostic NMS
        augment=False,  # augmented inference
        visualize=False,  # visualize features
        half=False,  # use FP16 half-precision inference
        dnn=False,  # use OpenCV DNN for ONNX inference
        ):
    source = str(source)
    if not source.endswith(clean_path.split(".")[-1]):
        raise ValueError("File must have same format as clean image!")

    # Load model
    device=torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    device = select_device(device)
    model = DetectMultiBackend(weights, device=device, dnn=dnn)

    model.requires_grad_(False)

    stride, pt, jit = model.stride, model.pt, model.jit

    # Half
    half &= pt and device.type != 'cpu'  # half precision only supported by PyTorch on CUDA
    if pt:
        model.model.half() if half else model.model.float()

    clean_img = cv2.imread(clean_path)
    clean_img = cv2.cvtColor(clean_img, cv2.COLOR_BGR2RGB)
    clean_img = torch.from_numpy(clean_img).to(device)
    clean_img = clean_img.float() / 255
    clean_img = clean_img[None].permute(0,3,1,2)

    dataset = LoadImages(clean_path, img_size=imgsz, stride=stride, auto=pt and not jit)

    # Run inference

    for path, im, im0s, vid_cap, s in dataset:
        im = torch.from_numpy(im).to(device)
        im = im.half() if half else im.float()  # uint8 to fp16/32
        im /= 255  # 0 - 255 to 0.0 - 1.0

        if len(im.shape) == 3:
            im = im[None]  # expand for batch dim

        im.requires_grad_(True)

        assert im.shape == clean_img.shape, "Image shapes must match."
        # im = im * mask + clean_img * (1 - mask) # eval patch
        # Inference
        # print('---------------------Start detecting----------------------')

        # 首次运行，选择梯度绝对值最大的 20480 个像素

        # pred = model(im, augment=augment, visualize=visualize)
        # conf = pred[0, :, 4].sum()
        # print('box置信度总和', conf.detach())

        # conf.backward()
        # # print(im.grad)

        # t = [
        #     (im.grad[0, :, x, y].abs().sum(), x, y) 
        #         for x in range(640) 
        #             for y in range(640)]
        # t.sort(reverse=True)

        # # print(t)

        # pixels = [x[1:] for x in t[:
20480]]
        # pickle.dump(pixels, open('pixels.pkl', 'wb'))
        pixels = pickle.load(open('pixels.pkl', 'rb'))
        
        mask = torch.zeros_like(im)
        for x, y in pixels:
            mask[0, :, x, y] = 1
        

        img = mask.detach().permute(0,2,3,1).numpy()[0] * 255
        img = img.round().astype(np.uint8)
        # print(img)
        Image.fromarray(img).save(f'out/mask.png')

        opti = torch.optim.Adam([im], lr=.1)

        for epoch in range(100):
            pred = model(im, augment=augment, visualize=visualize)
            conf = pred[0, :, 4].sum()

            
            pred = non_max_suppression(pred, conf_thres, iou_thres, classes, agnostic_nms, max_det=max_det)

            pr = pred[0].cpu()
            
            print(f'epoch #{epoch}','box置信度总和', conf.detach(), '预测 box 个数', len(pr))

            conf.backward()
            opti.step()

            
            im.data = torch.clamp(im.data, min=0.0, max=1.0)
            im.data = im * mask + clean_img * (1 - mask)
            im.grad.zero_()

            # print(im.detach())
            pickle.dump(im.detach(), open(f'out/im{epoch}.pkl', 'wb'))
            
            img = im.detach().permute(0,2,3,1).numpy()[0] * 255
            img = img.round().astype(np.uint8)
            # print(img)
            Image.fromarray(img).save(f'out/{epoch}.png')

def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', nargs='+', type=str, default='yolov5l.pt', help='model path(s)')
    parser.add_argument('--source', type=str, default='adv_images/stop.png', help='file/dir/URL/glob')
    parser.add_argument('--clean_path', type=str, default='images/stop.png', help='clean_img')
    parser.add_argument('--mask_path', type=str, default='adv_images/mask.png', help='mask_img')
    parser.add_argument('--imgsz', '--img', '--img-size', nargs='+', type=int, default=[640], help='inference size h,w')
    parser.add_argument('--conf-thres', type=float, default=0.25, help='confidence threshold')
    parser.add_argument('--iou-thres', type=float, default=0.45, help='NMS IoU threshold')
    parser.add_argument('--max-det', type=int, default=1000, help='maximum detections per image')
    parser.add_argument('--device', default='cpu', help='cuda device, i.e. 0 or 0,1,2,3 or cpu')
    parser.add_argument('--classes', nargs='+', type=int, help='filter by class: --classes 0, or --classes 0 2 3')
    parser.add_argument('--agnostic-nms', action='store_true', help='class-agnostic NMS')
    parser.add_argument('--augment', action='store_true', help='augmented inference')
    parser.add_argument('--visualize', action='store_true', help='visualize features')
    parser.add_argument('--half', action='store_true', help='use FP16 half-precision inference')
    parser.add_argument('--dnn', action='store_true', help='use OpenCV DNN for ONNX inference')
    opt = parser.parse_args()
    opt.imgsz *= 2 if len(opt.imgsz) == 1 else 1  # expand
    # print_args(FILE.stem, opt)
    return opt

def main(opt):
    run(**vars(opt))
    

if __name__ == "__main__":
    opt = parse_opt()
    main(opt)
