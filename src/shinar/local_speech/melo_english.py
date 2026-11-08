"""Melo English adapter over pinned, offline runtime frontends and weights.

The runtime supplies the audited melo/melo_text packages; weight packages do not
execute entrypoint scripts. This keeps multilingual frontend imports isolated.
"""

import json
import os
import re
import sys
from pathlib import Path


class MeloEnglish:
    def __init__(self, spec, threads):
        import numpy as np
        import torch
        from transformers import AutoModelForMaskedLM, AutoTokenizer

        self.torch, self.np = torch, np
        self.device = spec["provider"]
        torch.set_num_threads(threads)
        torch.manual_seed(9321)
        if self.device == "cuda":
            torch.cuda.set_device(spec.get("gpu_index", 0))
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable; no CPU fallback")
        os.environ["SHINAR_EVAL_BERT_DIR"] = spec["bert_path"]
        # The pinned support wheel still reads its original private variable.
        os.environ["LINGUALOOP_EVAL_BERT_DIR"] = spec["bert_path"]
        sys.path[:0] = [spec["melo_source"], spec["frontend_source"]]
        from melo.models import SynthesizerTrn
        from melo.split_utils import split_sentence
        from melo import commons
        from melo_text import english
        from melo_text.symbols import language_id_map, language_tone_start_map

        self.frontend, self.split = english, split_sentence
        self.intersperse = commons.intersperse
        self.language_id = language_id_map["EN"]
        self.tone_start = language_tone_start_map["EN"]
        config = json.loads(Path(spec["config_file"]).read_text(encoding="utf-8"))
        self.config, self.rate = config, config["data"]["sampling_rate"]
        self.symbol_to_id = {s: i for i, s in enumerate(config["symbols"])}
        self.model = SynthesizerTrn(
            len(config["symbols"]),
            config["data"]["filter_length"] // 2 + 1,
            config["train"]["segment_size"] // config["data"]["hop_length"],
            n_speakers=config["data"]["n_speakers"],
            num_tones=config["num_tones"],
            num_languages=config["num_languages"],
            **config["model"],
        )
        checkpoint = torch.load(spec["model_file"], map_location="cpu", weights_only=True)
        self.model.load_state_dict(checkpoint["model"], strict=True)
        self.model.eval().to(self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(spec["bert_path"], local_files_only=True)
        self.bert = (
            AutoModelForMaskedLM.from_pretrained(spec["bert_path"], local_files_only=True)
            .eval()
            .to(self.device)
        )

    def inputs(self, text):
        torch = self.torch
        norm = self.frontend.text_normalize(text)
        phones, tones, word2ph = self.frontend.g2p(norm)
        phone_ids = [self.symbol_to_id[x] for x in phones]
        tone_ids = [x + self.tone_start for x in tones]
        language_ids = [self.language_id] * len(phone_ids)
        if self.config["data"]["add_blank"]:
            phone_ids = self.intersperse(phone_ids, 0)
            tone_ids = self.intersperse(tone_ids, 0)
            language_ids = self.intersperse(language_ids, 0)
            word2ph = [x * 2 for x in word2ph]
            word2ph[0] += 1
        encoded = {
            k: v.to(self.device) for k, v in self.tokenizer(norm, return_tensors="pt").items()
        }
        assert encoded["input_ids"].shape[-1] == len(word2ph)
        with torch.no_grad():
            states = self.bert(**encoded, output_hidden_states=True).hidden_states[-3][0].cpu()
        english_bert = torch.cat(
            [states[i].repeat(count, 1) for i, count in enumerate(word2ph)], dim=0
        ).T
        assert english_bert.shape[-1] == len(phone_ids)
        tensor = lambda values: torch.LongTensor(values).to(self.device).unsqueeze(0)
        return (
            tensor(phone_ids),
            tensor(tone_ids),
            tensor(language_ids),
            torch.zeros(1, 1024, len(phone_ids), device=self.device),
            english_bert.to(self.device).unsqueeze(0),
        )

    def synthesize(self, text, speaker_id):
        torch, np = self.torch, self.np
        if self.device == "cuda":
            torch.cuda.synchronize()
        chunks = []
        for segment in self.split(text, language_str="EN"):
            segment = re.sub(r"([a-z])([A-Z])", r"\1 \2", segment)
            phones, tones, languages, bert, english_bert = self.inputs(segment)
            with torch.no_grad():
                audio = (
                    self.model.infer(
                        phones,
                        torch.LongTensor([phones.shape[1]]).to(self.device),
                        torch.LongTensor([speaker_id]).to(self.device),
                        tones,
                        languages,
                        bert,
                        english_bert,
                        sdp_ratio=0.2,
                        noise_scale=0.6,
                        noise_scale_w=0.8,
                        length_scale=1.0,
                    )[0][0, 0]
                    .data.cpu()
                    .float()
                    .numpy()
                )
            chunks.extend([audio, np.zeros(int(self.rate * 0.05), dtype=np.float32)])
        if self.device == "cuda":
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        return np.concatenate(chunks).astype(np.float32), self.rate
