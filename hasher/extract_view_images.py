"""Extract view images from a UI screenshot"""

import argparse
import csv
import json
import os
import shutil
import sys
import time
from os import makedirs, walk, listdir
from os.path import exists, join

import cv2

curpath = os.path.abspath(os.path.dirname(__file__))
rootpath = os.path.split(curpath)[0]
if rootpath not in sys.path:
    sys.path.append(rootpath)


from xml2nodes import XMLReader


def extract_view_imgs_from_xml(xml_parent_dir: str, xml_name: str,
                               skip_existance: bool, naive_xml: bool = False) -> int:
    """ use opencv to split a ui screenshot to extract its view images

    Args:
        xml_name (str): the name of the target hierarchy tree
        xml_parent_dir (str): the parent dir of xml_name
        skip_existance (bool): if true, skip the existance item
        naive_xml (bool): false when using uiautomator2 xml, if the hierarchy
            is dumped by naive adb, then true
    Return:
        view images count
    """
    save_path = join(xml_parent_dir, xml_name[:-4])
    if exists(save_path):
        if skip_existance:
            return len([a for a in listdir(save_path) if
                        a.endswith('.jpg')])
        else:
            shutil.rmtree(save_path)

    # generate new files
    makedirs(save_path)

    view_list = XMLReader(join(xml_parent_dir, xml_name),
                          naive_xml=naive_xml).node_dicts
    jpg_path = join(xml_parent_dir, f"{xml_name[:-4]}.jpg")
    img = cv2.imread(jpg_path, 1)
    if img is None:
        return 0
    k = 0
    for i, n in enumerate(view_list):
        _class = n['name']
        for _invalid_prefix in ['aux', 'com1', 'com2', 'prn', 'con', 'nul']:
            if _class.startswith(_invalid_prefix):
                _class = '_' + _class
                break
        view_img_path = join(save_path, f"{i}_{_class}.jpg")
        lt, rb = n["lt"], n["rb"]
        (h1, v1), (h2, v2) = lt, rb
        h1, v1, h2, v2 = int(h1), int(v1), int(h2), int(v2)

        new_img = img[v1:v2, h1:h2]
        if new_img.shape[0] == 0 or new_img.shape[1] == 0:
            # the xml is not with the jpg
            # (e.g., one is landscape and the other is not)
            continue
        try:
            cv2.imwrite(view_img_path, new_img)
            k += 1
        except cv2.error as e:
            print(f'CV2ERR: {e} for', view_img_path)
    return k


def extract_view_imgs(folder: str, skip_existance: bool = True,
                      naive_xml: bool = False):
    """ walk a given folder and extract view images for all hierarchy trees in it

    Args:
        folder (str): the target folder. Each subfolder in it contains
            hierarchy trees and the corresponding screenshot images for an app
        skip_existance (bool): if true, skip the existance items
        naive_xml (bool): false when using uiautomator2 xml, if the hierarchy
            is dumped by naive adb, then true
    """
    all_xml = []
    for dirpath, dirname, filenames in walk(folder):
        for name in filenames:
            if name.endswith('.xml'):
                all_xml.append([dirpath, name])
    total = len(all_xml)
    k, total_views = 0, 0
    for xml in all_xml:
        xml_parent_dir, xml_name = xml
        views = extract_view_imgs_from_xml(xml_parent_dir, xml_name,
                                           skip_existance, naive_xml)
        k += 1
        total_views += views
        print(f'({k}/{total}) {xml}')
    print(f'done! {total_views} views in total.')


def read_rico_json_nodes(nodes: list, o: dict):
    """ read rico json files"""
    if "componentLabel" in o:
        nodes.append([*o["bounds"], o["componentLabel"]])
    if "children" in o:
        for c in o["children"]:
            read_rico_json_nodes(nodes, c)


def extract_view_imgs_from_rico(rico_root_path: str):
    """
    extract view images from rico dataset

    Args:
        rico_root_path (str): the parent path where you put all rico files
            (unzipped) in it
    """
    json_path = join(rico_root_path, "semantic_annotations")
    metas = []
    with open(join(rico_root_path, "ui_details.csv"), mode="r") as f:
        f_csv = csv.reader(f)
        for line in f_csv:
            metas.append(line)
    print("load meta csv done")
    m = 0
    for k, line in enumerate(metas[40000:]):
        index, app, trace, number = line
        with open(join(json_path, f"{index}.json"), mode="r", encoding="utf-8") as f:
            jo = json.load(f)
        jpg_path = join(rico_root_path, "filtered_traces",
                        app, f"trace_{trace}", "screenshots", f"{number}.jpg")

        views = []
        read_rico_json_nodes(views, jo)
        ui_img = cv2.imread(jpg_path, 1)
        ui_img_h, ui_img_w, _ = ui_img.shape
        ui_img_original_h, ui_img_original_w, _ = cv2.imread(join(json_path, f"{index}.png")).shape
        w_scale = float(ui_img_w) / ui_img_original_w
        h_scale = float(ui_img_h) / ui_img_original_h
        if ui_img is None:
            continue
        for n in views:
            w1, h1, w2, h2, label = n
            w1 = int(w1 * w_scale)
            w2 = int(w2 * w_scale)
            h1 = int(h1 * h_scale)
            h2 = int(h2 * h_scale)
            img = ui_img[h1:h2, w1:w2]
            if img.shape[0] == 0 or img.shape[1] == 0:
                continue
            try:
                img_save_path = join(rico_root_path, "views", label)
                if not exists(img_save_path):
                    makedirs(img_save_path)
                cv2.imwrite(join(img_save_path, f"{m}.jpg"), img)
                m += 1
            except cv2.error as e:
                print(f'CV2ERR: {e}')
        k += 1
        if k % 1000 == 0:
            print(k)


def extract_view_imgs_from_web(folder: str):
    """
    extract view images from web crawler output (json + png)
    """
    files = [f for f in listdir(folder) if f.endswith('.json')]
    total = len(files)
    print(f"Found {total} json files in {folder}")
    
    m = 0
    for k, json_file in enumerate(files):
        json_path = join(folder, json_file)
        # Corresponding png file
        png_file = json_file.replace('.json', '.png')
        png_path = join(folder, png_file)
        
        if not exists(png_path):
            print(f"Image not found for {json_file}")
            continue
            
        try:
            with open(json_path, mode="r", encoding="utf-8") as f:
                jo = json.load(f)
            
            ui_img = cv2.imread(png_path, 1)
            if ui_img is None:
                print(f"Failed to load image: {png_path}")
                continue

            views = []
            read_rico_json_nodes(views, jo)
            
            # Create per-screen directory
            screen_dir_name = json_file[:-5] # remove .json
            screen_dir_path = join(folder, screen_dir_name)
            if not exists(screen_dir_path):
                makedirs(screen_dir_path)
            
            # Save the xml (json) there too as uihash.py expects an xml file in the folder
            # We will just copy the json as .xml for now or keep it as json and adapt uihash?
            # uihash.py looks for .xml. Let's create a dummy xml or just rename the json to .xml?
            # Actually uihash.py uses XMLReader. XMLReader expects XML.
            # We might need to adapt uihash.py later. For now let's just save the images.
            # Wait, uihash.py iterates over folders and looks for xmls.
            # "xmls = [i for i in xmls if i.endswith("xml")]"
            # So we MUST have an xml file in that folder. 
            # Since we are doing "Web" adaptation, we should probably adapt uihash.py to read json too.
            # But for this step (extraction), let's just focus on images.
            
            for n in views:
                # Rico format: [x1, y1, x2, y2, label]
                w1, h1, w2, h2, label = n
                w1, h1, w2, h2 = int(w1), int(h1), int(w2), int(h2)
                
                # Clip coordinates to image bounds
                h, w, _ = ui_img.shape
                w1 = max(0, min(w1, w))
                w2 = max(0, min(w2, w))
                h1 = max(0, min(h1, h))
                h2 = max(0, min(h2, h))
                
                if w2 <= w1 or h2 <= h1:
                    continue

                img = ui_img[h1:h2, w1:w2]
                if img.shape[0] == 0 or img.shape[1] == 0:
                    continue
                
                try:
                    # Save to screen_dir/m_label.jpg
                    # Sanitize label for filename
                    safe_label = "".join([c if c.isalnum() else "_" for c in label])
                    img_filename = f"{m}_{safe_label}.jpg"
                    cv2.imwrite(join(screen_dir_path, img_filename), img)
                    m += 1
                except cv2.error as e:
                    print(f'CV2ERR: {e}')
                    
        except Exception as e:
            print(f"Error processing {json_file}: {e}")
            
        if (k+1) % 10 == 0:
            print(f"Processed {k+1}/{total}")

    print(f"Done! Extracted {m} views.")


def parse_arg_extract_view_images(input_args: list):
    parser = argparse.ArgumentParser(description="Extract view images from UIs, "
                                                 "support UI hierarchy printed by "
                                                 "naive adb, uiautomator2 and rico")
    parser.add_argument("input_path",
                        help="the path where UI hierarchy exists")
    parser.add_argument("--rico", "-r", action="store_true", default=False,
                        help="extract view images from rico UIs")
    parser.add_argument("--web", "-w", action="store_true", default=False,
                        help="extract view images from web crawler output")
    parser.add_argument("--naivexml", "-n", action="store_true",
                        help="assign it when using naive adb, "
                             "and ignore it when using uiautomator2 xml")
    parser.add_argument("--skip", "-s", action="store_true", default=True,
                        help="skip the existance items")
    _args = parser.parse_args(input_args)
    return _args


if __name__ == '__main__':
    args = parse_arg_extract_view_images(sys.argv[1:])
    t1 = time.perf_counter()
    if args.rico:
        extract_view_imgs_from_rico(args.input_path)
    elif args.web:
        extract_view_imgs_from_web(args.input_path)
    else:
        extract_view_imgs(args.input_path,
                          skip_existance=args.skip, naive_xml=args.naivexml)
    t2 = time.perf_counter()
    print("time cost:", t2 - t1)
