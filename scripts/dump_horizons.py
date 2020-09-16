""" Predict horizons-mask using saved model and dump largest horizons on disk. """
#pylint: disable=import-error, wrong-import-position
import os
import sys
import argparse
import json
import logging

import pandas as pd
from tqdm import tqdm

sys.path.append('..')
from seismiqb import SeismicCubeset, dump_horizon
from seismiqb.batchflow import Pipeline, FilesIndex, B, V, L, D
from seismiqb.batchflow.models.tf import TFModel



def main(path_to_cube, path_to_model, path_to_predictions, gpu_device,
         cube_crop, crop_shape, crop_stride, area_share, threshold, printer=None):
    """ Main function. """
    # Set gpu-device
    os.environ['CUDA_VISIBLE_DEVICES'] = str(gpu_device)

    # Init Cubeset and load cube-geometries
    dsix = FilesIndex(path=path_to_cube, no_ext=True)
    ds = SeismicCubeset(dsix)
    ds = ds.load_geometries()
    printer('Cube assembling is started')

    # Make grid for small crops
    ds = ds.make_grid(ds.indices[0], crop_shape, *cube_crop, crop_stride)

    # Pipeline: slice crops, normalize values in the cube, make predictions
    # via model, assemble crops according to the grid
    load_config = {'load/path': path_to_model}
    predict_pipeline = (Pipeline()
                        .load_component(src=D('geometries'), dst='geometries')
                        .crop(points=L(D('grid_gen')), shape=crop_shape)
                        .load_cubes(dst='data_crops')
                        .rotate_axes(src='data_crops')
                        .scale(mode='normalize', src='data_crops')
                        .init_model('dynamic', TFModel, 'loaded_model', load_config)
                        .init_variable('result_preds', init_on_each_run=list())
                        .predict_model('loaded_model', fetches='sigmoid', cubes=B('data_crops'),
                                       save_to=V('result_preds', mode='e')))

    predict_pipeline.run(1, n_iters=ds.grid_iters, bar='n')
    assembled_pred = ds.assemble_crops(predict_pipeline.v('result_preds'))

    printer('Cube is assembled')

    # Fetch and dump horizons
    prediction = assembled_pred
    ds.get_point_cloud(prediction, 'horizons', coordinates='lines', threshold=threshold)
    printer('Horizonts are labeled')

    if (not os.path.exists(path_to_predictions)) and \
       (not os.path.isdir(path_to_predictions)):
        os.mkdir(path_to_predictions)

    ds.horizons.sort(key=len, reverse=True)
    area = (cube_crop[0][1] - cube_crop[0][0]) * (cube_crop[1][1] - cube_crop[1][0])

    ctr = 0
    for h in ds.horizons:
        if len(h) / area >= area_share:
            dump_horizon(h, ds.geometries[ds.indices[0]],
                         os.path.join(path_to_predictions, 'Horizon_' + str(ctr)))
            printer('Horizont {} is saved'.format(ctr))
            ctr += 1


if __name__ == '__main__':
    # Fetch path to config
    parser = argparse.ArgumentParser(description="Predict horizons on a part of seismic-cube.")
    parser.add_argument("--config_path", type=str, default="./configs/dump.json")
    args = parser.parse_args()

    # Fetch main-arguments from config
    with open(args.config_path, 'r') as file:
        config = json.load(file)
        args = [config.get(key) for key in ["cubePath", "modelPath", "predictionsPath", "gpuDevice",
                                            "cubeCrop", "cropShape", "cropStride", "areaShare", "threshold"]]

    # Logging to either stdout or file
    if config.get("print"):
        printer = print
    else:
        path_log = config.get("path_log") or os.path.join(os.getcwd(), "logs/dump.log")
        print('LOGGING TO ', path_log)
        handler = logging.FileHandler(path_log, mode='w')
        handler.setFormatter(logging.Formatter('%(asctime)s     %(message)s'))

        logger = logging.getLogger('train_logger')
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        printer = logger.info

    main(*args, printer=printer)
