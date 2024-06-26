import numpy as np
import argparse
import os
import tensorflow as tf
from PIL import Image # Pillow
from io import BytesIO
import glob
import matplotlib.pyplot as plt

from object_detection.utils import ops as utils_ops
from object_detection.utils import label_map_util
from object_detection.utils import visualization_utils as vis_util

import pandas as pd

# patch tf1 into `utils.ops`
utils_ops.tf = tf.compat.v1

# Patch the location of gfile
tf.gfile = tf.io.gfile


def load_model(model_path):
    model = tf.saved_model.load(model_path)
    return model


def load_image_into_numpy_array(path):
    """Load an image from file into a numpy array.

    Puts image into numpy array to feed into tensorflow graph.
    Note that by convention we put it into a numpy array with shape
    (height, width, channels), where channels=3 for RGB.

    Args:
      path: a file path (this can be local or on colossus)

    Returns:
      uint8 numpy array with shape (img_height, img_width, 3)
    """
    img_data = tf.io.gfile.GFile(path, 'rb').read()
    image = Image.open(BytesIO(img_data))
    (im_width, im_height) = image.size
    return np.array(image.getdata()).reshape(
        (im_height, im_width, 3)).astype(np.uint8)


def run_inference_for_single_image(model, image):
    # The input needs to be a tensor, convert it using `tf.convert_to_tensor`.
    input_tensor = tf.convert_to_tensor(image)
    # The model expects a batch of images, so add an axis with `tf.newaxis`.
    input_tensor = input_tensor[tf.newaxis, ...]

    # Run inference
    output_dict = model(input_tensor)

    # All outputs are batches tensors.
    # Convert to numpy arrays, and take index [0] to remove the batch dimension.
    # We're only interested in the first num_detections.
    num_detections = int(output_dict.pop('num_detections'))
    output_dict = {key: value[0, :num_detections].numpy()
                   for key, value in output_dict.items()}
    output_dict['num_detections'] = num_detections

    # detection_classes should be ints.
    output_dict['detection_classes'] = output_dict['detection_classes'].astype(np.int64)

    # Handle models with masks:
    if 'detection_masks' in output_dict:
        # Reframe the the bbox mask to the image size.
        detection_masks_reframed = utils_ops.reframe_box_masks_to_image_masks(
            output_dict['detection_masks'], output_dict['detection_boxes'],
            image.shape[0], image.shape[1])
        detection_masks_reframed = tf.cast(detection_masks_reframed > 0.5, tf.uint8)
        output_dict['detection_masks_reframed'] = detection_masks_reframed.numpy()

    df = output_to_csv(output_dict)
    df.to_csv('detections.csv')
    return df


def output_to_csv(od):
    min_score = 0.5
    remove_keys = ['raw_detection_scores', 'raw_detection_boxes', 'detection_multiclass_scores', 'detection_anchor_indices', 'num_detections']
    for key in remove_keys:
        od.pop(key)
    above_min = 0
    for score in od['detection_scores']:
        if score >= min_score:
            above_min+=1
        else:
            break
          
    i = above_min  
    classes, x_min, y_min, x_max, y_max = [], [], [], [], []
    for box in od['detection_boxes']:
        if i == 0:
            break
        # remove * 512 and round for relative coordinates
        y_min.append(round(box[0] * 512))
        x_min.append(round(box[1] * 512))
        y_max.append(round(box[2] * 512))
        x_max.append(round(box[3] * 512))
        i -= 1
    i = above_min
    for nr in od['detection_classes']:
        if i == 0:
            break
        classes.append(category_index[nr]['name'])
        i-=1
    
    od.pop('detection_boxes')
    od.pop('detection_classes')
    df = pd.DataFrame(od).head(len(y_max))
    df['class'] = classes
    df['x min'] = x_min
    df['y min'] = y_min
    df['x max'] = x_max
    df['y max '] = y_max
    
    return df
def run_inference(model, category_index, image_path):
    if os.path.isdir(image_path):
        image_paths = []
        for file_extension in ('*.png', '*jpg'):
            image_paths.extend(glob.glob(os.path.join(image_path, file_extension)))

        """add iterator here"""
        i = 0
        for i_path in image_paths:
            image_np = load_image_into_numpy_array(i_path)
            # Actual detection.
            output_dict = run_inference_for_single_image(model, image_np)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Detect objects inside webcam videostream')
    parser.add_argument('-m', '--model', type=str, required=True, help='Model Path')
    parser.add_argument('-l', '--labelmap', type=str, required=True, help='Path to Labelmap')
    parser.add_argument('-i', '--image_path', type=str, required=True, help='Path to image (or folder)')
    args = parser.parse_args()

    print("loading model")
    detection_model = load_model(args.model)
    print("loading labelmap")
    category_index = label_map_util.create_category_index_from_labelmap(args.labelmap, use_display_name=True)
    print("running inference")
    run_inference(detection_model, category_index, args.image_path)
    print("done")

# Command to start script
#  python .\detect_from_images.py -m ssd_mobilenet_v2_320x320_coco17_tpu-8\saved_model -l .\data\mscoco_label_map.pbtxt -i .\test_images