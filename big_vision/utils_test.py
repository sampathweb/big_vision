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

"""Tests for utils."""

from functools import partial
from absl.testing import parameterized
from big_vision import utils
import chex
import flax
import jax
import numpy as np
import tensorflow as tf

NDEV = 4


def setUpModule():
  chex.set_n_cpu_devices(NDEV)


class PadShardUnpadTest(chex.TestCase, tf.test.TestCase):
  BATCH_SIZES = [NDEV, NDEV + 1, NDEV - 1, 5 * NDEV, 5 * NDEV + 1, 5 * NDEV - 1]
  DTYPES = [np.float32, np.uint8, jax.numpy.bfloat16, np.int32]

  def tearDown(self):
    chex.clear_trace_counter()
    super().tearDown()

  @parameterized.product(dtype=DTYPES, bs=BATCH_SIZES)
  def test_basics(self, dtype, bs):
    # Just tests that basic calling works without exploring caveats.
    @partial(utils.pad_shard_unpad, static_argnums=())
    def add(a, b):
      return a + b

    x = np.arange(bs, dtype=dtype)
    y = add(x, 10*x)
    chex.assert_type(y.dtype, x.dtype)
    np.testing.assert_allclose(np.float64(y), np.float64(x + 10*x))

  @parameterized.parameters(DTYPES)
  def test_min_device_batch_avoids_recompile(self, dtype):
    @partial(utils.pad_shard_unpad, static_argnums=())
    @jax.jit
    @chex.assert_max_traces(n=1)
    def add(a, b):
      return a + b

    chex.clear_trace_counter()

    for bs in self.BATCH_SIZES:
      x = np.arange(bs, dtype=dtype)
      y = add(x, 10*x, min_device_batch=9)  # pylint: disable=unexpected-keyword-arg
      chex.assert_type(y.dtype, x.dtype)
      np.testing.assert_allclose(np.float64(y), np.float64(x + 10*x))

  @parameterized.product(dtype=DTYPES, bs=BATCH_SIZES)
  def test_static_argnum(self, dtype, bs):
    @partial(utils.pad_shard_unpad, static_argnums=(1,))
    def add(a, b):
      return a + b

    x = np.arange(bs, dtype=dtype)
    y = add(x, 10)
    chex.assert_type(y.dtype, x.dtype)
    np.testing.assert_allclose(np.float64(y), np.float64(x + 10))

  @parameterized.product(dtype=DTYPES, bs=BATCH_SIZES)
  def test_static_argnames(self, dtype, bs):
    # In this test, leave static_argnums at the default value too, in order to
    # test the default/most canonical path where `params` are the first arg.
    @partial(utils.pad_shard_unpad, static_argnames=('b',))
    def add(params, a, *, b):
      return params * a + b

    x = np.arange(bs, dtype=dtype)
    y = add(5, x, b=10)
    chex.assert_type(y.dtype, x.dtype)
    np.testing.assert_allclose(np.float64(y), np.float64(5 * x + 10))


class TreeTest(tf.test.TestCase):

  def setUp(self):
    super().setUp()

    self.d1 = {'w1': 1, 'w2': 2, 'w34': (3, 4)}
    self.d1_flat = [1, 2]
    self.d1_flat_jax = jax.tree_flatten(self.d1)[0]
    self.d1_named_flat = [('w1', 1), ('w2', 2), ('w34/0', 3), ('w34/1', 4)]
    self.d1_named_flat_jax = [('w1', 1), ('w2', 2), ('w34/0', 3), ('w34/1', 4)]

    self.d2 = {'conv1': {'kernel': 0, 'bias': 1},
               'conv2': {'kernel': 2, 'bias': 3}}
    self.d2_flat = [1, 0, 3, 2]
    self.d2_flat_jax = jax.tree_flatten(self.d2)[0]
    self.d2_named_flat = [('conv1/bias', 1), ('conv1/kernel', 0),
                          ('conv2/bias', 3), ('conv2/kernel', 2)]
    self.d2_named_flat_jax = [('conv1/bias', 1), ('conv1/kernel', 0),
                              ('conv2/bias', 3), ('conv2/kernel', 2)]

    # This is a very important testcase that checks whether we correctly
    # recover jax' traversal order, even though our custom traversal may not
    # be consistent with jax' traversal order. In particular, jax traverses
    # FlaxStruct in the order of attribute definition, while our custom
    # traversal is alphabetical.
    @flax.struct.dataclass
    class FlaxStruct():
      v3: float
      v2: int
      v1: str
    self.d3 = {'a': 0, 'flax': FlaxStruct(2.0, 1, 's')}
    self.d3_flat = [0, 1, 2.0, 's']
    self.d3_flat_jax = jax.tree_flatten(self.d3)[0]
    self.d3_named_flat = [
        ('a', 0), ('flax/v1', 's'), ('flax/v2', 1), ('flax/v3', 2.0)]
    self.d3_named_flat_jax = [
        ('a', 0), ('flax/v3', 2.0), ('flax/v2', 1), ('flax/v1', 's')]

  def test_traverse_with_names(self):
    names_and_vals = list(utils._traverse_with_names(self.d1))
    self.assertEqual(names_and_vals, self.d1_named_flat)

    names_and_vals = list(utils._traverse_with_names(self.d2))
    self.assertEqual(names_and_vals, self.d2_named_flat)

    names_and_vals = list(utils._traverse_with_names(self.d3))
    self.assertEqual(names_and_vals, self.d3_named_flat)

  def test_tree_flatten_with_names(self):
    names_and_vals = utils.tree_flatten_with_names(self.d1)[0]
    self.assertEqual(names_and_vals, self.d1_named_flat_jax)
    self.assertEqual([x for _, x in names_and_vals], self.d1_flat_jax)

    names_and_vals = utils.tree_flatten_with_names(self.d2)[0]
    self.assertEqual(names_and_vals, self.d2_named_flat_jax)
    self.assertEqual([x for _, x in names_and_vals], self.d2_flat_jax)

    names_and_vals = utils.tree_flatten_with_names(self.d3)[0]
    self.assertEqual(names_and_vals, self.d3_named_flat_jax)
    self.assertEqual([x for _, x in names_and_vals], self.d3_flat_jax)

  def test_tree_map_with_names(self):
    d1 = utils.tree_map_with_names(
        lambda name, x: -x if 'w2' in name else x, self.d1)
    self.assertEqual(d1, {'w1': 1, 'w2': -2, 'w34': (3, 4)})

    d1 = utils.tree_map_with_names(
        lambda name, x1, x2: x1 + x2 if 'w2' in name else x1, self.d1, self.d1)
    self.assertEqual(d1, {'w1': 1, 'w2': 4, 'w34': (3, 4)})

  def test_recover_tree(self):
    keys = ['a/b', 'a/c/x', 'a/c/y', 'd']
    values = [0, 1, 2, 3]
    self.assertEqual(utils.recover_tree(keys, values),
                     {'a': {'b': 0, 'c': {'x': 1, 'y': 2}}, 'd': 3})

  def test_make_mask_trees(self):
    F, T = False, True  # pylint: disable=invalid-name
    tree = {'a': {'b': 0, 'x': 1}, 'b': {'x': 2, 'y': 3}}
    msk1 = {'a': {'b': F, 'x': T}, 'b': {'x': T, 'y': F}}
    msk2 = {'a': {'b': F, 'x': F}, 'b': {'x': F, 'y': T}}
    # Note that 'b' matches '^b' only and not '.*/b'.
    # Also note that "b/x" is matched by rule 1 only (because it comes first).
    self.assertEqual(
        utils.make_mask_trees(tree, ('.*/x', 'b/.*')), [msk1, msk2])


class CreateLearningRateScheduleTest(parameterized.TestCase, tf.test.TestCase):

  @parameterized.named_parameters(
      ('linear', 'linear', {}, 13, .5),
      ('polynomial', 'polynomial', {'end': .1, 'power': 2}, 13, .325),
      ('cosine', 'cosine', {}, 13, .5),
      ('rsqrt', 'rsqrt', {'timescale': 1}, 13, 0.3333333),
      ('stair_5', 'stair', {'steps': [10], 'mults': [.5]}, 5, 1.),
      ('stair_10', 'stair', {'steps': [10], 'mults': [.5]}, 10, .5),
      ('warmup_before', 'rsqrt', {'timescale': 1}, 3, .6),
      ('cooldown_after', 'rsqrt', {'timescale': 1}, 20, .05),
  )
  def test_schedule(self, decay_type, extra_kwargs, step, expected_lr):
    lr_fn = utils.create_learning_rate_schedule(
        global_batch_size=512,
        total_steps=21,
        steps_per_epoch=None,
        base=.5,
        decay_type=decay_type,
        scale_with_batchsize=True,
        warmup_steps=5,
        cooldown_steps=5,
        **extra_kwargs)
    lr = lr_fn(step)
    self.assertAlmostEqual(lr, expected_lr)


if __name__ == '__main__':
  tf.test.main()
