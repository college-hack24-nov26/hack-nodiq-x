# JIS G5502-2022 ISO法、JIS法による球状化率の判定
# coding: utf-8
try:
    import tkinter
    from tkinter import filedialog
except (ImportError, ModuleNotFoundError):
    tkinter = None
    filedialog = None
import cv2
import os
import sys
import datetime
import math
from pathlib import Path

# https://www.rectus.co.jp/archives/18
# pythonのprintでエラーになるときの対応
# Do not reassign sys.stdin/stdout/stderr on import: this breaks pytest's
# output capture and can close the process streams unexpectedly. The legacy
# module is imported by the active pipeline and should remain side-effect free.

# 環境設定
iDir='C:/Data' # 画像ファイルが格納されているフォルダ
pic_width=1920 # 入力画像のサイズによらず、画像処理や出力画像はこの幅に設定
    # pic_height（高さ）は入力画像の幅と高さの比から計算
min_grainsize=0.0071 # 画像の幅に対する黒鉛の最小長さ（撮影した画像に応じて設定が必要）
    # min_grainsize=0.007はサンプル画像に対する値である。
    # サンプル画像は幅142mmに表示させると、倍率100倍の組織画像になる。
    # この場合、黒鉛の最小長さ（10μm）は1mmとなる。1mm÷142mm=0.007→min_grainsize
marumi_ratio = 0.6 #iso法で形状ⅤとⅥと判定する丸み係数のしきい値

# 検出方法の設定
USE_ROBUST_DETECTION = True
USE_ORIGINAL_DETECTION_FALLBACK = False
DEBUG = False
BACKGROUND_BLUR_SIZE = 201 # 背景推定用のガウシアンぼかしサイズ（奇数）
MORPHOLOGY_KERNEL_SIZE = 15
MIN_CONTOUR_AREA = 1000
MAX_CONTOUR_AREA_RATIO = 0.15
MIN_CIRCULARITY = 0.08
MIN_SOLIDITY = 0.45

# ダイアログ形式によるファイル選択
def get_picture_filenames():
    root=tkinter.Tk()
    root.withdraw()
    fTyp = [("jpg", "*.jpg"), ("BMP", "*.bmp"), ("png", "*.png"), ("tiff", "*.tif")] 
    filenames = filedialog.askopenfilenames(title='画像ファイルを選んでください', filetypes=fTyp, initialdir=iDir) 
    return filenames

# contoursからmin_grainsize未満の小さい輪郭と、画像の端に接している輪郭を除いてcoutours1に格納
def select_contours(contours, pic_width, pic_height, min_grainsize):
    contours1 = []
    for e, cnt in enumerate(contours):
        x_rect, y_rect, w_rect, h_rect = cv2.boundingRect(cnt)
        (x_circle, y_circle), radius_circle = cv2.minEnclosingCircle(cnt)
        if int(pic_width * min_grainsize) <= 2 * radius_circle \
            and 0 < int(x_rect) and 0 < int(y_rect) and \
            int(x_rect + w_rect) < pic_width and int(y_rect + h_rect) < pic_height:
            contours1.append(cnt)  
    return contours1

# 背景テクスチャを除いた輪郭を、面積・円形度・凸度で選別
def select_robust_contours(contours, pic_width, pic_height, min_grainsize):
    contours1 = select_contours(contours, pic_width, pic_height, min_grainsize)
    max_contour_area = pic_width * pic_height * MAX_CONTOUR_AREA_RATIO
    selected_contours = []
    for cnt in contours1:
        contour_area = cv2.contourArea(cnt)
        if contour_area < MIN_CONTOUR_AREA or contour_area > max_contour_area:
            continue
        perimeter = cv2.arcLength(cnt, True)
        if perimeter == 0:
            continue
        circularity = 4 * math.pi * contour_area / (perimeter ** 2)
        hull = cv2.convexHull(cnt)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            continue
        solidity = contour_area / hull_area
        if circularity >= MIN_CIRCULARITY and solidity >= MIN_SOLIDITY:
            selected_contours.append(cnt)
    return selected_contours

# 均一でない照明を除き、暗い黒鉛を明るい前景として抽出
def detect_graphite_contours(img_gray, pic_width, pic_height, min_grainsize):
    background = cv2.GaussianBlur(
        img_gray, (BACKGROUND_BLUR_SIZE, BACKGROUND_BLUR_SIZE), 0
    )
    img_normalized = cv2.subtract(background, img_gray)
    img_normalized = cv2.normalize(img_normalized, None, 0, 255, cv2.NORM_MINMAX)
    _, threshold_image = cv2.threshold(
        img_normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    morphology_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE,
        (MORPHOLOGY_KERNEL_SIZE, MORPHOLOGY_KERNEL_SIZE)
    )
    opened = cv2.morphologyEx(threshold_image, cv2.MORPH_OPEN, morphology_kernel)
    cleaned_binary = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, morphology_kernel)
    contours, hierarchy = cv2.findContours(
        cleaned_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    selected_contours = select_robust_contours(
        contours, pic_width, pic_height, min_grainsize
    )
    return selected_contours, img_normalized, threshold_image, cleaned_binary

# 輪郭の長軸の中心座標と、最遠点対の半分の長さを求める（キャリパ法）
def get_graphite_length(hull):
    max_distance = 0
    for i, hull_x in enumerate(hull):
        for j, hull_y in enumerate(hull):
            if j + 1 < len(hull) and i != j + 1:
                dis_x = hull[j+1][0][0] - hull[i][0][0]
                dis_y = hull[j+1][0][1] - hull[i][0][1]
                dis = math.sqrt(dis_x**2 + dis_y**2)
                if dis > max_distance:
                    max_distance = dis # 最遠点対の距離を更新
                    x = dis_x * 0.5 + hull[i][0][0] # 最遠点対の中点を更新
                    y = dis_y * 0.5 + hull[i][0][1] # 最遠点対の中点を更新
    return(x, y, max_distance * 0.5) # 最遠点対の半分の長さ（円の半径）

def main():
    # input_images内の対応画像をすべて処理
    base_dir = Path(__file__).resolve().parent
    input_dir = base_dir / "input_images"
    annotated_dir = base_dir / "annotated_images"
    labels_dir = base_dir / "labels"
    annotated_dir.mkdir(exist_ok=True)
    labels_dir.mkdir(exist_ok=True)
    debug_dir = base_dir / "debug_images"
    if DEBUG:
        debug_dir.mkdir(exist_ok=True)
    filenames = sorted(
        str(path) for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not filenames:
        sys.exit("input_imagesフォルダにjpg、jpeg、またはpng画像がありません。")

    # 画像ファイルごとの球状化率はこの変数に格納
    nodularity_ISO = []
    nodularity_JIS = []

    for filename in filenames:

        # 画像ファイルの読み込み、サイズ取得（パス名に全角があるとエラーになる）
        img_color_ISO= cv2.imread(filename) # カラーで出力表示させるためカラーで読み込み
        img_height, img_width, channel = img_color_ISO.shape # 画像のサイズ取得
        
        # 画像処理や出力画像のサイズ計算（pic_width, pic_height）
        pic_height=int(pic_width * img_height / img_width)
        img_color_ISO = cv2.resize(img_color_ISO, (pic_width, pic_height)) # 読み込んだ画像ファイルのサイズ変換
        img_color_JIS = img_color_ISO.copy() #img_colorのコピーの作成
        img_color_annotated = img_color_ISO.copy()
        
        # カラー→グレー変換、二値化、輪郭の検出、球状化率の評価に用いる輪郭の選別
        img_gray = cv2.cvtColor(img_color_ISO, cv2.COLOR_BGR2GRAY)
        if USE_ROBUST_DETECTION:
            contours1, img_normalized, threshold_image, cleaned_binary = detect_graphite_contours(
                img_gray, pic_width, pic_height, min_grainsize
            )
            if not contours1 and USE_ORIGINAL_DETECTION_FALLBACK:
                _, img_inv_binary = cv2.threshold(
                    img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
                )
                contours, hierarchy = cv2.findContours(
                    img_inv_binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
                )
                contours1 = select_contours(
                    contours, pic_width, pic_height, min_grainsize
                )
        else:
            img_normalized = img_gray
            _, threshold_image = cv2.threshold(
                img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )
            cleaned_binary = threshold_image
            contours, hierarchy = cv2.findContours(
                threshold_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
            )
            contours1 = select_contours(
                contours, pic_width, pic_height, min_grainsize
            )

        if DEBUG:
            image_stem = Path(filename).stem
            cv2.imwrite(str(debug_dir / (image_stem + "_grayscale.png")), img_gray)
            cv2.imwrite(str(debug_dir / (image_stem + "_normalized.png")), img_normalized)
            cv2.imwrite(str(debug_dir / (image_stem + "_threshold.png")), threshold_image)
            cv2.imwrite(str(debug_dir / (image_stem + "_cleaned_binary.png")), cleaned_binary)

        # 黒鉛の面積と黒鉛の長軸の中心座標、長軸の半分の長さの計算、丸み係数の算出
        sum_graphite_areas = 0
        sum_graphite_areas_5and6 = 0
        num_graphite1 = num_graphite2 = num_graphite3 = num_graphite4 = num_graphite5 = 0
        label_lines = []

        for i, cnt in enumerate(contours1): 
            graphite_area = cv2.contourArea(cnt)
            sum_graphite_areas += graphite_area
            x_rect, y_rect, w_rect, h_rect = cv2.boundingRect(cnt)
            center_x = (x_rect + w_rect / 2) / pic_width
            center_y = (y_rect + h_rect / 2) / pic_height
            width = w_rect / pic_width
            height = h_rect / pic_height
            label_lines.append("0 {:.6f} {:.6f} {:.6f} {:.6f}".format(
                center_x, center_y, width, height
            ))
            cv2.drawContours(img_color_annotated, contours1, i, (0, 0, 255), 2)
            hull = cv2.convexHull(cnt) # 凸包
            x, y, graphite_radius = get_graphite_length(hull) # 輪郭の長軸の中心座標（x, y）と長軸の半分の長さ(graphite_radius)
            marumi = graphite_area / ((graphite_radius ** 2) * math.pi) #丸み係数

            # ISO法による形状ⅤとⅥの黒鉛の判定し、それらの黒鉛の輪郭を赤色で描画
            if marumi >= marumi_ratio:
                sum_graphite_areas_5and6 += graphite_area
                cv2.drawContours(img_color_ISO, contours1, i, (0, 0, 255), 2)

            # JIS法による形状分類
            if marumi <= 0.2:
                num_graphite1 += 1
                cv2.drawContours(img_color_JIS, contours1, i, (255, 255, 0), 2) #水色
            if 0.2 < marumi <= 0.4:
                num_graphite2 += 1
                cv2.drawContours(img_color_JIS, contours1, i, (0, 255, 0), 2) #緑
            if 0.4 < marumi <= 0.7:
                num_graphite3 += 1
                cv2.drawContours(img_color_JIS, contours1, i, (128, 0, 128), 2) #紫
            if 0.7 < marumi <= 0.8:
                num_graphite4 += 1
                cv2.drawContours(img_color_JIS, contours1, i, (255, 0, 0), 2) #青
            if 0.8 < marumi:
                num_graphite5 += 1
                cv2.drawContours(img_color_JIS, contours1, i, (0, 0,255), 2) #赤
                    
        # 球状化率（ISO法）
        nodularity_ISO.append(sum_graphite_areas_5and6 / sum_graphite_areas * 100)
        # 球状化率（JIS法）
        nodularity_JIS.append((0.3 * num_graphite2 + 0.7 * num_graphite3 + 0.9 * num_graphite4 + 1.0 * num_graphite5)/ len(contours1) * 100)
        
        # 画像ファイルの保存
        src = filename
        idx = src.rfind(r'.')
        result_ISO_filename = src[:idx] + "_nodularity(ISO)." + src[idx+1:]
        result_JIS_filename = src[:idx] + "_nodularity(JIS)." + src[idx+1:]
        cv2.imwrite(result_ISO_filename, img_color_ISO)
        cv2.imwrite(result_JIS_filename, img_color_JIS)
        image_path = Path(filename)
        cv2.imwrite(str(annotated_dir / image_path.name), img_color_annotated)
        with open(labels_dir / (image_path.stem + ".txt"), mode="w", encoding="utf-8") as label_file:
            label_file.write("\n".join(label_lines))

    # 球状化率などのデータの保存
    now = datetime.datetime.now()

    output_file = str(os.path.dirname(filenames[0])) + '/nodularity_{0:%Y%m%d%H%M}'.format(now) + ".csv"

    with open(output_file, mode='w', encoding='utf-8') as f1:
        print("最小黒鉛サイズ, {:.3f}".format(min_grainsize), file = f1)
        print("丸み係数のしきい値, {:.3f}".format(marumi_ratio), file = f1)
        print("画像処理と出力画像の幅, {}".format(pic_width), file = f1)
        print("ファイル名, 球状化率_ISO法(%), 球状化率_JIS法(%)", file = f1)
        for i in range(len(filenames)):
            print("{}, {:.2f}, {:.2f}" .format(filenames[i], nodularity_ISO[i], nodularity_JIS[i]), file = f1)

            
if __name__ == "__main__":
    main()
