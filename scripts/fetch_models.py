"""Скачать модели в models/ перед сборкой (в репозиторий они не кладутся).

GigaAM v3 (int8) и Silero VAD — с Hugging Face (istupakov/*), 3D-Speaker CAM++ — из релизов sherpa-onnx.
"""
import os, shutil, sys, urllib.request

from huggingface_hub import hf_hub_download

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MODELS = os.path.join(ROOT, "models")

ASR = ("istupakov/gigaam-v3-onnx", ["config.json", "v3_e2e_rnnt.yaml", "v3_e2e_rnnt_vocab.txt", "LICENSE.txt",
                                    "v3_e2e_rnnt_encoder.int8.onnx", "v3_e2e_rnnt_decoder.int8.onnx",
                                    "v3_e2e_rnnt_joint.int8.onnx"])
VAD = ("istupakov/silero-vad-onnx", ["config.json", "silero_vad.onnx", "LICENSE.txt"])
VOICE = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
         "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")


def fetch(repo, files, folder):
    os.makedirs(folder, exist_ok=True)
    for f in files:
        dst = os.path.join(folder, f)
        if not os.path.exists(dst):
            try:
                shutil.copy(hf_hub_download(repo, f), dst)
            except Exception as e:
                if f.startswith("LICENSE") or f.endswith(".yaml"):
                    print(f"нет {f} в {repo}: {e}", file=sys.stderr)
                    continue
                raise
        print("ok", repo, f)


def main():
    fetch(*ASR, os.path.join(MODELS, "gigaam-v3"))
    fetch(*VAD, os.path.join(MODELS, "silero-vad"))
    dst = os.path.join(MODELS, "3dspeaker_campplus.onnx")
    if not os.path.exists(dst):
        urllib.request.urlretrieve(VOICE, dst)
    print("ok 3dspeaker")


if __name__ == "__main__":
    main()
