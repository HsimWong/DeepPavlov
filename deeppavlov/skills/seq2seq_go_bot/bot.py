"""
Copyright 2017 Neural Networks and Deep Learning lab, MIPT

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import itertools
import numpy as np
from typing import Type

from deeppavlov.core.common.registry import register
from deeppavlov.core.models.nn_model import NNModel
from deeppavlov.core.data.vocab import DefaultVocabulary
from deeppavlov.models.embedders.fasttext_embedder import FasttextEmbedder
from deeppavlov.models.encoders.bow import BoWEncoder
from deeppavlov.skills.seq2seq_go_bot.network import Seq2SeqGoalOrientedBotNetwork
from deeppavlov.core.common.log import get_logger


log = get_logger(__name__)


@register("seq2seq_go_bot")
class Seq2SeqGoalOrientedBot(NNModel):
    def __init__(self,
                 end_of_sequence_token,
                 start_of_sequence_token,
                 network: Type = Seq2SeqGoalOrientedBotNetwork,
                 source_vocab: Type = DefaultVocabulary,
                 target_vocab: Type = DefaultVocabulary,
                 bow_encoder: Type = BoWEncoder,
                 knowledge_base_keys: Type = list,
                 debug=False,
                 save_path=None,
                 **kwargs):

        super().__init__(save_path=save_path, mode=kwargs['mode'])

        self.sos_token = start_of_sequence_token
        self.eos_token = end_of_sequence_token
        self.network = network
        self.src_vocab = source_vocab
        self.tgt_vocab = target_vocab
        self.tgt_vocab_size = len(target_vocab)
        self.bow_encoder = bow_encoder
        self.kb_keys = knowledge_base_keys
        self.kb_size = len(self.kb_keys)
        #self.embedder = embedder
        self.debug = debug

    def train_on_batch(self, *batch):
        b_enc_ins, b_src_lens, b_kb_masks = [], [], []
        b_dec_ins, b_dec_outs, b_tgt_lens, b_tgt_weights = [], [], [], []
        for x_tokens, history, kb_entries, y_tokens in zip(*batch):

            x_tokens = history + x_tokens
            enc_in = self._encode_context(x_tokens)
            b_enc_ins.append(enc_in)
            b_src_lens.append(len(enc_in))
            if self.debug:
                if len(kb_entries) != len(set([e[0] for e in kb_entries])):
                    print("Duplicates in kb_entries = {}".format(kb_entries))
            b_kb_masks.append(self._kb_mask(kb_entries))

            dec_in, dec_out = self._encode_response(y_tokens)
            b_dec_ins.append(dec_in)
            b_dec_outs.append(dec_out)
            b_tgt_lens.append(len(dec_out))
            b_tgt_weights.append([1] * len(dec_out))

        # Sequence padding
        max_src_len = max(b_src_lens)
        max_tgt_len = max(b_tgt_lens)
        for i, (src_len, tgt_len) in enumerate(zip(b_src_lens, b_tgt_lens)):
            src_padd_len = max_src_len - src_len
            tgt_padd_len = max_tgt_len - tgt_len
            b_enc_ins[i].extend([self.src_vocab[self.sos_token]] * src_padd_len)
            b_dec_ins[i].extend([self.tgt_vocab[self.eos_token]] * tgt_padd_len)
            b_dec_outs[i].extend([self.tgt_vocab[self.eos_token]] * tgt_padd_len)
            b_tgt_weights[i].extend([0] * tgt_padd_len)

        self.network.train_on_batch(b_enc_ins, b_dec_ins, b_dec_outs,
                                    b_src_lens, b_tgt_lens, b_tgt_weights, b_kb_masks)

    def _encode_context(self, tokens):
        if self.debug:
            log.debug("Context tokens = \"{}\"".format(tokens))
        token_idxs = self.src_vocab(tokens)
        return token_idxs

    def _kb_mask(self, entries):
        mask = np.zeros(self.kb_size, dtype=np.float32)
        for k, v in entries:
            mask[self.kb_keys.index(k)] = 1.
        return mask

    def _encode_response(self, tokens):
        if self.debug:
            log.debug("Response tokens = \"{}\"".format(y_tokens))
        token_idxs = []
        for token in tokens:
            if token in self.tgt_vocab:
                token_idxs.append(self.tgt_vocab[token])
            else:
                if token not in self.kb_keys:
                    print("token = {}, tokens = {}".format(token, tokens))
                token_idxs.append(self.tgt_vocab_size + self.kb_keys.index(token))
        # token_idxs = self.tgt_vocab(tokens)
        return ([self.tgt_vocab[self.sos_token]] + token_idxs,
                token_idxs + [self.tgt_vocab[self.eos_token]])

    def _decode_response(self, token_idxs):
        def _idx2token(idxs):
            for idx in idxs:
                if idx < self.tgt_vocab_size:
                    token = self.tgt_vocab([idx])[0]
                    if token == self.eos_token:
                        break
                    yield token
                else:
                    yield self.kb_keys[idx - self.tgt_vocab_size]
        return [list(_idx2token(utter_idxs)) for utter_idxs in token_idxs]

    def __call__(self, *batch):
        return self._infer_on_batch(*batch)

    #def _infer_on_batch(self, utters, kb_entry_list=itertools.repeat([])):
    def _infer_on_batch(self, utters, history_list, kb_entry_list):
# TODO: history as input
        b_enc_ins, b_src_lens, b_kb_masks = [], [], []
        if (len(utters) == 1) and not utters[0]:
            utters = [['hi']]
        for utter, history, kb_entries in zip(utters, history_list, kb_entry_list):
            if self.debug:
                log.debug("infer: kb_entries = {}".format(kb_entries))
            utter = history + utter
            enc_in = self._encode_context(utter)
            b_enc_ins.append(enc_in)
            b_src_lens.append(len(enc_in))
            b_kb_masks.append(self._kb_mask(kb_entries))

        # Sequence padding
        max_src_len = max(b_src_lens)
        for i, src_len in enumerate(b_src_lens):
            src_padd_len = max_src_len - src_len
            b_enc_ins[i].extend([self.src_vocab[self.eos_token]] * src_padd_len)

        pred_idxs = self.network(b_enc_ins, b_src_lens, b_kb_masks)
        preds = self._decode_response(pred_idxs)
        if self.debug:
            log.debug("Dialog prediction = \"{}\"".format(preds[-1]))
        return preds

    def save(self):
        self.network.save()

    def load(self):
        pass
