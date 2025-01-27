import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'

import pytorch_lightning as pl
from pytorch_lightning.loggers import WandbLogger
from omegaconf import DictConfig
import hydra

from src.domain_adaptation.cyclegan.cyclegan import CycleGAN
from src.datasets.unity import UnityDataset, UnityDataModule
from src.datasets.nyudv2 import NYUDv2Dataset, NYUDv2DataModule
from src.datasets.bdsd500 import BDSD500Dataset, BDSD500DataModule
from src.datasets.domain_transfer import DomainTransfer

from src.segmentation.models.bdcn import BDCN

@hydra.main(config_path="config", config_name="config", version_base="1.1.0")
def main(cfg: DictConfig) -> None:
    pl.seed_everything(42)

    # Create model
    model = BDCN()

    logger = WandbLogger(
        name=cfg.train.name,
        project='Segmentation',
        config=dict(cfg)
    )

    # profiler = pl.profilers.AdvancedProfiler(dirpath='.', filename='results.txt')
    trainer = pl.Trainer(logger=logger, max_epochs=cfg.train.epochs, devices=cfg.train.gpus, log_every_n_steps=5)

    # Create dataset
    if cfg.data.dataset == "bdsd500":
        dataset = BDSD500Dataset(cfg.data.root_bdsd500, resize=tuple(cfg.data.resize), crop_size=tuple(cfg.data.crop_size))
        data_module = BDSD500DataModule(dataset, batch_size=cfg.data.batch_size)
    elif cfg.data.dataset == "nyudv2":
        dataset = NYUDv2Dataset(cfg.data.root_nyudv2, resize=False, crop_size=tuple(cfg.data.crop_size))
        data_module = NYUDv2DataModule(dataset, batch_size=cfg.data.batch_size)
    elif cfg.data.dataset == "unity":
        dataset = UnityDataset(crop_size=tuple(cfg.data.crop_size))
        data_module = UnityDataModule(dataset, batch_size=cfg.data.batch_size)
    else:
        raise ValueError("Invalid dataset")
    
    if cfg.data.domain_transfer:
        checkpoint_path = cfg.data.checkpoint_path
        cycleGAN = CycleGAN()
        domain_transfer = DomainTransfer(cycleGAN, checkpoint_path)

        train_dataloader = domain_transfer.generate(data_module.train_dataloader())
        val_dataloader = domain_transfer.generate(data_module.val_dataloader())
    else:
        train_dataloader = data_module.train_dataloader()
        val_dataloader = data_module.val_dataloader()

    # Train the model
    trainer.fit(model, train_dataloader, val_dataloader)

if __name__ == "__main__":
    main()
