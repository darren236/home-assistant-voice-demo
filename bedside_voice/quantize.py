"""Quantize TTS dense layers; retain the streaming codec in FP32."""
import gc
import json
from pathlib import Path
import shutil
import tempfile


def quantize(root):
    import onnx
    import onnxruntime as ort
    from onnxruntime.quantization import QuantType, quantize_dynamic
    source = root / "models"
    output = root / "models-int8"
    if output.exists():
        raise RuntimeError("models-int8 already exists; move it aside to preserve the previous conversion")
    work = root / "quant-work"
    work.mkdir(parents=True, exist_ok=True)
    folder = 'MOSS-TTS-Nano-100M-ONNX'
    target = output / folder
    target.mkdir(parents=True, exist_ok=True)
    for name in ('browser_poc_manifest.json', 'tts_browser_onnx_meta.json', 'tokenizer.model'):
        shutil.copy2(source / folder / name, target / name)
    summary = dict(onnx=onnx.__version__, onnxruntime=ort.__version__,
        method='ORT basic optimization then per-channel dynamic QInt8 constant-weight MatMul', models=[])
    for name in ('moss_tts_prefill.onnx', 'moss_tts_decode_step.onnx', 'moss_tts_local_fixed_sampled_frame.onnx'):
        print('Converting', name, flush=True)
        with tempfile.TemporaryDirectory(prefix='bedside-int8-', dir=work) as temporary:
            temporary = Path(temporary)
            # External-data references remain valid if ORT preserves them.
            for data in (source / folder).glob('*.data'):
                shutil.copy2(data, temporary / data.name)
            basic = temporary / 'basic.onnx'
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            options.add_session_config_entry('session.intra_op.allow_spinning', '0')
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
            options.optimized_model_filepath = str(basic)
            session = ort.InferenceSession(str(source / folder / name), options, providers=['CPUExecutionProvider'])
            expected_inputs = [x.name for x in session.get_inputs()]
            del session
            gc.collect()
            quant = temporary / 'quant' / name
            quant.parent.mkdir()
            quantize_dynamic(str(basic), str(quant), op_types_to_quantize=['MatMul', 'Gemm'],
                per_channel=True, weight_type=QuantType.QInt8, use_external_data_format=True,
                extra_options={'MatMulConstBOnly': True, 'WeightSymmetric': True})
            options.optimized_model_filepath = ''
            checked = ort.InferenceSession(str(quant), options, providers=['CPUExecutionProvider'])
            if [x.name for x in checked.get_inputs()] != expected_inputs:
                raise RuntimeError('Quantized model changed the input contract')
            del checked
            gc.collect()
            graph = onnx.load(quant, load_external_data=False)
            integer_nodes = sum(n.op_type in ('MatMulInteger', 'DynamicQuantizeMatMul') for n in graph.graph.node)
            if not integer_nodes:
                raise RuntimeError('No dense layers were quantized')
            files = list(quant.parent.iterdir())
            for file in files:
                shutil.copy2(file, target / file.name)
            record = dict(model=name, integer_nodes=integer_nodes,
                          bytes=sum(p.stat().st_size for p in files), ir=graph.ir_version)
            summary['models'].append(record)
            print(json.dumps(record), flush=True)
    codec = 'MOSS-Audio-Tokenizer-Nano-ONNX'
    (output / codec).mkdir(parents=True, exist_ok=True)
    for name in ('codec_browser_onnx_meta.json', 'moss_audio_tokenizer_decode_step.onnx',
                 'moss_audio_tokenizer_decode_shared.data'):
        shutil.copy2(source / codec / name, output / codec / name)
    (output / 'quantization.json').write_text(json.dumps(summary, indent=2)+'\n')
    print('Completed separate INT8 TTS bundle; codec remains float32', flush=True)
