"""Bounded real CUDA optimizer/backward and restart probe. No market orders."""
import argparse
import json
import os
import pathlib
import time
import torch
from brain_factory import thermal, save_checkpoint
from brain_factory_models import SequenceModel
from brain_research import write


def probe(directory):
    directory.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable')
    torch.cuda.set_per_process_memory_fraction(.20)
    thermal()
    reports = []
    for kind in ('mlp', 'tcn', 'gru', 'lstm', 'transformer', 'moe'):
        torch.manual_seed(7301)
        net = SequenceModel(kind).cuda().train()
        opt = torch.optim.AdamW(net.parameters(), lr=.001)
        path = directory / (kind + '.pt')
        steps = 0
        if path.exists():
            state = torch.load(path, map_location='cpu', weights_only=True)
            net.load_state_dict(state['model'])
            opt.load_state_dict(state['optimizer'])
            steps = state['steps']
        before = [p.detach().clone() for p in net.parameters()]
        x = torch.randn(8, 16, 6, 8, device='cuda')
        with torch.autocast('cuda', dtype=torch.float16):
            loss = net(x).float().square().mean()
        loss.backward()
        # MoE has expert heads; SequenceModel's common head is intentionally unused.
        grads = [p.grad for name, p in net.named_parameters() if p.requires_grad
                 and not (kind == 'moe' and name.startswith('head.'))]
        if not torch.isfinite(loss) or any(g is None or not torch.isfinite(g).all() for g in grads):
            raise RuntimeError('Missing/nonfinite backward gradients: ' + kind)
        opt.step()
        torch.cuda.synchronize()
        delta = sum(float((p.detach()-b).abs().sum()) for p, b in zip(net.parameters(), before))
        if delta <= 0:
            raise RuntimeError('Optimizer did not change weights: ' + kind)
        save_checkpoint(path, dict(model=net.state_dict(), optimizer=opt.state_dict(), steps=steps+1))
        reports.append(dict(kind=kind, loss=float(loss.detach()), parameter_delta=delta,
                            restored_steps=steps, completed_steps=steps+1))
        del net, opt
    result = dict(pid=os.getpid(), updated_ms=int(time.time()*1000),
                  gpu=torch.cuda.get_device_name(), torch=torch.__version__,
                  cudnn=torch.backends.cudnn.version(), temperature=thermal(),
                  library_path=os.environ.get('LD_LIBRARY_PATH'), models=reports,
                  passed=True, trading_evidence=False)
    write(directory / ('probe-' + str(time.time_ns()) + '.json'), result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=pathlib.Path, required=True)
    probe(parser.parse_args().directory)
