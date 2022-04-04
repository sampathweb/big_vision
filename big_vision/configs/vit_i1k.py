# Copyright 2022 Big Vision Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# pylint: disable=line-too-long
r"""Pre-training ViT on ILSVRC-2012 as in https://arxiv.org/abs/2106.10270

This configuration makes use of the "arg" to get_config to select which model
to run, so a few examples are given below:

Run training of a B/16 model:

big_vision.train \
    --config big_vision/configs/vit_i1k.py:variant=B/16 \
    --workdir gs://[your_bucket]/big_vision/`date '+%m-%d_%H%M'`

Run training of a B/32 model with custom aug-strenght and 300ep:

big_vision.train \
    --config big_vision/configs/vit_i1k.py:variant=B/32,aug=light1 \
    --workdir gs://[your_bucket]/big_vision/`date '+%m-%d_%H%M'` \
    --config.num_epochs 300
"""

import big_vision.configs.common as bvcc
from big_vision.configs.common_fewshot import get_fewshot_lsr
import ml_collections as mlc

MIXUP_DEF = {
    'none': dict(p=0.0, fold_in=None),
    'light1': dict(p=0.0, fold_in=None),
    'light2': dict(p=0.2, fold_in=None),
    'medium1': dict(p=0.2, fold_in=None),
    'medium2': dict(p=0.5, fold_in=None),
    'strong1': dict(p=0.5, fold_in=None),
    'strong2': dict(p=0.8, fold_in=None),
}

RANDAUG_DEF = {
    'none': '',
    'light1': 'randaug(2,0)',  # Actually not nothing!
    'light2': 'randaug(2,10)',
    'medium1': 'randaug(2,15)',
    'medium2': 'randaug(2,15)',
    'strong1': 'randaug(2,20)',
    'strong2': 'randaug(2,20)',
}


def get_config(arg=None):
  """Config for training."""
  arg = bvcc.parse_arg(arg, variant='B/16', runlocal=False, aug='')
  config = mlc.ConfigDict()

  # If this gives a KeyError, lookup Fig4 of the paper and add an entry.
  # Note, this here is a good average between 30ep and 300ep, sometimes you coud
  # find a slightly better setting for either of them.
  aug_setting = arg.aug or {
      'Ti/16': 'light1',
      'S/32': 'light2',
      'S/16': 'medium2',
      'B/32': 'medium2',
      'B/16': 'medium2',
      'L/16': 'medium2',
  }[arg.variant]

  config.dataset = 'imagenet2012'
  config.train_split = 'train[:99%]'
  config.cache_raw = not arg.runlocal  # Needs up to 120GB of RAM!
  config.shuffle_buffer_size = 250_000  # Per host, so small-ish is ok.
  config.num_classes = 1000
  config.loss = 'softmax_xent'
  config.batch_size = 4096
  config.num_epochs = 300

  pp_common = (
      '|value_range(-1, 1)'
      '|onehot(1000, key="{lbl}", key_result="labels")'
      '|keep("image", "labels")'
  )
  config.pp_train = (
      'decode_jpeg_and_inception_crop(224)|flip_lr|' +
      RANDAUG_DEF[aug_setting] +
      pp_common.format(lbl='label')
  )
  pp = 'decode|resize_small(256)|central_crop(224)' + pp_common

  # Aggressive pre-fetching because our models here are small, so we not only
  # can afford it, but we also need it for the smallest models to not be
  # bottle-necked by the input pipeline. Play around with it for -L models tho.
  config.prefetch_to_host = 8
  config.prefetch_to_device = 4

  config.log_training_steps = 50
  config.log_eval_steps = 1000
  config.checkpoint_steps = 1000

  # Model section
  config.model_name = 'vit'
  config.model = dict(
      variant=arg.variant,
      rep_size=True,
      pool_type='tok',
  )

  # Optimizer section
  config.grad_clip_norm = 1.0
  config.optax_name = 'scale_by_adam'
  config.optax = dict(mu_dtype='bfloat16')
  # The modified AdaFactor we introduced in https://arxiv.org/abs/2106.04560
  # almost always behaves exactly like adam, but at a fraction of the memory
  # cost (specifically, adam_bf16 = +1.5M, adafactor = +0.5M), hence it is a
  # good idea to try it when you are memory-bound!
  # config.optax_name = 'big_vision.scale_by_adafactor'
  # A good flag to play with when hitting instabilities, is the following:
  # config.optax = dict(beta2_cap=0.95)

  config.lr = 0.001
  config.wd = 0.0001
  config.schedule = dict(warmup_steps=10_000, decay_type='cosine')

  config.mixup = MIXUP_DEF[aug_setting]

  # Eval section
  config.evals = [
      ('minival', 'classification'),
      ('val', 'classification'),
      ('real', 'classification'),
      ('v2', 'classification'),
      ('fewshot', 'fewshot_lsr'),
  ]

  eval_common = dict(
      pp_fn=pp.format(lbl='label'),
      loss_name=config.loss,
      log_steps=1000,
  )

  config.minival = dict(**eval_common)
  config.minival.dataset = 'imagenet2012'
  config.minival.split = 'train[99%:]'

  config.val = dict(**eval_common)
  config.val.dataset = 'imagenet2012'
  config.val.split = 'validation'

  config.real = dict(**eval_common)
  config.real.dataset = 'imagenet2012_real'
  config.real.split = 'validation'
  config.real.pp_fn = pp.format(lbl='real_label')

  config.v2 = dict(**eval_common)
  config.v2.dataset = 'imagenet_v2'
  config.v2.split = 'test'

  config.fewshot = get_fewshot_lsr()
  config.fewshot.log_steps = 10_000

  # Make a few things much smaller for quick local debugging testruns.
  if arg.runlocal:
    config.shuffle_buffer_size = 10
    config.batch_size = 8
    config.minival.split = 'train[:16]'
    config.val.split = 'validation[:16]'
    config.real.split = 'validation[:16]'
    config.v2.split = 'test[:16]'

  return config