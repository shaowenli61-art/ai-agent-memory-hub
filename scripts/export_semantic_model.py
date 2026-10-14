"""Export already-local BGE CLS embeddings at full precision; no downloads."""
import argparse
import json
import os
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',default='config/operations_dashboard.json')
    p.add_argument('--output',required=True)
    args=p.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    model_path=Path(config['semantic_model_path'])
    pooling=json.loads((model_path/'1_Pooling/config.json').read_text(encoding='utf-8'))
    if not pooling.get('pooling_mode_cls_token') or pooling.get('pooling_mode_mean_tokens'):
        raise ValueError('当前导出器仅适用于已核验的 BGE CLS 池化模型。')
    os.environ['HF_HUB_OFFLINE']='1'
    os.environ['TRANSFORMERS_OFFLINE']='1'
    import torch
    from transformers import AutoModel,AutoTokenizer
    torch.set_num_threads(4)
    model=AutoModel.from_pretrained(model_path,local_files_only=True).eval()
    tokenizer=AutoTokenizer.from_pretrained(model_path,local_files_only=True)
    class Embed(torch.nn.Module):
        def __init__(self):
            super().__init__();self.model=model
        def forward(self,input_ids,attention_mask,token_type_ids):
            cls=self.model(input_ids=input_ids,attention_mask=attention_mask,token_type_ids=token_type_ids).last_hidden_state[:,0]
            return torch.nn.functional.normalize(cls,p=2,dim=1)
    inputs=tokenizer(['测试本地检索'],return_tensors='pt')
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        raise ValueError('输出已存在，请使用新文件名，避免替换运行中的模型。')
    names=['input_ids','attention_mask','token_type_ids']
    torch.onnx.export(Embed(),tuple(inputs[k] for k in names),str(target),dynamo=False,
        input_names=names,output_names=['embeddings'],opset_version=17,
        dynamic_axes={k:{0:'batch',1:'sequence'} for k in names}|{'embeddings':{0:'batch'}})
    print(json.dumps(dict(ok=True,path=str(target.resolve()),precision='float32',offline=True)))


if __name__=='__main__':main()
