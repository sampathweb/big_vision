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
r"""A config for pre-training BiT on ImageNet-21k.

This config relies on the Imagenet-21k tfds dataset, which is not yet
available publicly in TFDS. We intend to add the dataset to public TFDS soon,
and this config will then be runnable.
"""

from big_vision.configs.common_fewshot import get_fewshot_lsr
import ml_collections as mlc


def get_config():
  """Config for training on imagenet-21k."""
  config = mlc.ConfigDict()

  config.dataset = 'imagenet21k'
  config.train_split = 'full[51200:]'
  config.num_classes = 21843
  config.init_head_bias = -10.0
  config.loss = 'sigmoid_xent'

  config.trial = 0
  config.batch_size = 4096
  config.num_epochs = 90

  pp_common = f'|value_range(-1, 1)|onehot({config.num_classes})'
  config.pp_train = 'decode_jpeg_and_inception_crop(224)|flip_lr' + pp_common
  pp_eval = 'decode|resize_small(256)|central_crop(224)' + pp_common
  config.shuffle_buffer_size = 250_000  # Per host, so small-ish is ok.

  config.log_training_steps = 50
  config.log_eval_steps = 1000
  # NOTE: eval is very fast O(seconds) so it's fine to run it often.
  config.checkpoint_steps = 1000

  # Model section
  config.model_name = 'bit'
  config.model = dict(depth=50, width=1.0)

  # Optimizer section
  config.optax_name = 'big_vision.momentum_hp'
  config.grad_clip_norm = 1.0

  # linear scaling rule. Don't forget to sweep if sweeping batch_size.
  config.lr = (0.03 / 256) * config.batch_size
  config.wd = (3e-5 / 256) * config.batch_size
  config.schedule = dict(decay_type='cosine', warmup_steps=5000)

  # Eval section
  config.evals = [
      ('val', 'classification'),
      ('test', 'classification'),
      ('fewshot', 'fewshot_lsr'),
  ]

  eval_common = dict(
      dataset=config.dataset,
      pp_fn=pp_eval,
      loss_name=config.loss,
      log_steps=1000,
  )
  config.val = dict(**eval_common)
  config.val.split = 'full[25600:51200]'
  config.test = dict(**eval_common)
  config.test.split = 'full[:25600]'

  config.fewshot = get_fewshot_lsr()
  config.fewshot.log_steps = 25_000

  return config