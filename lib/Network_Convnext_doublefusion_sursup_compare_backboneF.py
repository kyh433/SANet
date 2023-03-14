import torch
import torch.nn as nn
import torch.nn.functional as F
from lib.Res2Net_v1b import res2net50_v1b_26w_4s
from lib.convnext import convnext_base,convnext_small,convnext_tiny

from lib.featvis import *


class DecoderBlock(nn.Module):
    def __init__(self, in_channels, n_filters):
        super(DecoderBlock,self).__init__()

        self.conv1 = nn.Conv2d(in_channels, in_channels // 4, 1)
        self.norm1 = nn.BatchNorm2d(in_channels // 4)
        self.relu1 = partial(F.relu,inplace=True)

        self.deconv2 = nn.ConvTranspose2d(in_channels // 4, in_channels // 4, 3, stride=2, padding=1, output_padding=1)
        self.norm2 = nn.BatchNorm2d(in_channels // 4)
        self.relu2 = partial(F.relu,inplace=True)

        self.conv3 = nn.Conv2d(in_channels // 4, n_filters, 1)
        self.norm3 = nn.BatchNorm2d(n_filters)
        self.relu3 = partial(F.relu,inplace=True)

    def forward(self, x):
        x = self.conv1(x)
        x = self.norm1(x)
        x = self.relu1(x)
        x = self.deconv2(x)
        x = self.norm2(x)
        x = self.relu2(x)
        x = self.conv3(x)
        x = self.norm3(x)
        x = self.relu3(x)
        return x

class BasicConv2d(nn.Module):
    def __init__(self, in_planes, out_planes, kernel_size, stride=1, padding=0, dilation=1):
        super(BasicConv2d, self).__init__()
        self.conv = nn.Conv2d(in_planes, out_planes,
                              kernel_size=kernel_size, stride=stride,
                              padding=padding, dilation=dilation, bias=False)
        self.bn = nn.BatchNorm2d(out_planes)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        return x


class RFB_modified(nn.Module):
    def __init__(self, in_channel, out_channel):
        super(RFB_modified, self).__init__()
        self.relu = nn.ReLU(True)
        self.branch0 = nn.Sequential(
            BasicConv2d(in_channel, out_channel, 1),
        )
        self.branch1 = nn.Sequential(
            BasicConv2d(in_channel, out_channel, 1),
            BasicConv2d(out_channel, out_channel, kernel_size=(1, 3), padding=(0, 1)),
            BasicConv2d(out_channel, out_channel, kernel_size=(3, 1), padding=(1, 0)),
            BasicConv2d(out_channel, out_channel, 3, padding=3, dilation=3)
        )
        self.branch2 = nn.Sequential(
            BasicConv2d(in_channel, out_channel, 1),
            BasicConv2d(out_channel, out_channel, kernel_size=(1, 5), padding=(0, 2)),
            BasicConv2d(out_channel, out_channel, kernel_size=(5, 1), padding=(2, 0)),
            BasicConv2d(out_channel, out_channel, 3, padding=5, dilation=5)
        )
        self.branch3 = nn.Sequential(
            BasicConv2d(in_channel, out_channel, 1),
            BasicConv2d(out_channel, out_channel, kernel_size=(1, 7), padding=(0, 3)),
            BasicConv2d(out_channel, out_channel, kernel_size=(7, 1), padding=(3, 0)),
            BasicConv2d(out_channel, out_channel, 3, padding=7, dilation=7)
        )
        self.conv_cat = BasicConv2d(4*out_channel, out_channel, 3, padding=1)
        self.conv_res = BasicConv2d(in_channel, out_channel, 1)


    def forward(self, x):
        x0 = self.branch0(x)
        x1 = self.branch1(x)
        x2 = self.branch2(x)
        x3 = self.branch3(x)
        x_cat = self.conv_cat(torch.cat((x0, x1, x2, x3), 1))

        x = self.relu(x_cat + self.conv_res(x))
        return x


class NeighborConnectionDecoder(nn.Module):
    def __init__(self, channel):
        super(NeighborConnectionDecoder, self).__init__()
        self.upsample = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv_upsample1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2_1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2_2 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3_1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3_2 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample4 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample5 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_upsample6 = BasicConv2d(3*channel, 3*channel, 3, padding=1)

        self.conv_concat2 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_concat3 = BasicConv2d(3*channel, 3*channel, 3, padding=1)
        self.conv_concat4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv5 = nn.Conv2d(4*channel, 1, 1)

    def forward(self, x1, x2, x3, x4):
        x1_1 = x1
        x2_1 = self.conv_upsample1(self.upsample(x1)) * x2
        x3_1 = self.conv_upsample2_1(self.upsample(x2_1)) * self.conv_upsample2_2(self.upsample(x2)) * x3
        x4_1 = self.conv_upsample3_1(self.upsample(x3_1)) * self.conv_upsample3_2(self.upsample(x3)) * x4

        x2_2 = torch.cat((x2_1, self.conv_upsample4(self.upsample(x1_1))), 1)
        x2_2 = self.conv_concat2(x2_2)

        x3_2 = torch.cat((x3_1, self.conv_upsample5(self.upsample(x2_2))), 1)
        x3_2 = self.conv_concat3(x3_2)

        x4_2 = torch.cat((x4_1, self.conv_upsample6(self.upsample(x3_2))), 1)
        x4_2 = self.conv_concat4(x4_2)

        x = self.conv4(x4_2)
        x = self.conv5(x)

        return x


class EdgeDecoder2(nn.Module):
    def __init__(self, channel):
        super(EdgeDecoder2, self).__init__()
        self.upsample = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv_upsample1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2_1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3_1 = BasicConv2d(channel, channel, 3, padding=1)

        self.conv_upsample4 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample5 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_upsample6 = BasicConv2d(3*channel, 3*channel, 3, padding=1)

        self.conv_concat2 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_concat3 = BasicConv2d(3*channel, 3*channel, 3, padding=1)
        self.conv_concat4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv5 = nn.Conv2d(4*channel, 1, 1)

        # self.conve2_1 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        # self.conve2_2 = nn.Conv2d(2*channel, 1, 1)
        # self.conve3_1 = BasicConv2d(3*channel, 3*channel, 3, padding=1)
        # self.conve3_2 = nn.Conv2d(3*channel, 1, 1)

        # self.rfb2 = RFB_modified(64, channel)
        # self.rfb3 = RFB_modified(96, channel)
        # self.rfb4 = RFB_modified(128, channel)
        self.conv2_f = BasicConv2d(2*channel, channel, 3, padding=1)
        self.conv3_f = BasicConv2d(3*channel, channel, 3, padding=1)
        self.conv4_f = BasicConv2d(4*channel, channel, 3, padding=1)

    def forward(self, x1, x2, x3,x4):
        x1_1 = x1
        x2_1 = self.conv_upsample1(self.upsample(x1_1)) * x2
        x3_1 = self.conv_upsample2_1(self.upsample(x2_1)) * self.conv_upsample2(self.upsample(x2)) * x3
        x4_1 = self.conv_upsample3_1(self.upsample(x3_1)) * self.conv_upsample3(self.upsample(x3)) * x4


        x2_2 = torch.cat((x2_1, self.conv_upsample4(self.upsample(x1_1))), 1)  #channel+channel
        x2_2 = self.conv_concat2(x2_2) #18,32,88,88
        x2_2_conv = self.conv2_f(x2_2)

        # e2_1 = self.conve2_1(x2_2)
        # e2_2 = self.conve2_2(e2_1) #18,1,22,22

        x3_2 = torch.cat((x3_1, self.conv_upsample5(self.upsample(x2_2))), 1)  #2channel+channel
        x3_2 = self.conv_concat3(x3_2) #18,32,88,88
        x3_2_conv = self.conv3_f(x3_2)

        # e3_1 = self.conve3_1(x3_2)
        # e3_2 = self.conve3_2(e3_1) #18,1,22,22
        
        x4_2 = torch.cat((x4_1, self.conv_upsample6(self.upsample(x3_2))), 1)  #3channel+channel
        x4_2 = self.conv_concat4(x4_2) #18,128,88,88
        x4_2_conv = self.conv4_f(x4_2)

        x = self.conv4(x4_2)
        x = self.conv5(x)

        return x2_2_conv,x3_2_conv,x4_2_conv,x


class SurroundDecoder(nn.Module):
    def __init__(self, channel):
        super(SurroundDecoder, self).__init__()
        self.upsample = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=True)
        self.conv_upsample1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample2_1 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample3_1 = BasicConv2d(channel, channel, 3, padding=1)

        self.conv_upsample4 = BasicConv2d(channel, channel, 3, padding=1)
        self.conv_upsample5 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_upsample6 = BasicConv2d(3*channel, 3*channel, 3, padding=1)

        self.conv_concat2 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.conv_concat3 = BasicConv2d(3*channel, 3*channel, 3, padding=1)
        self.conv_concat4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv4 = BasicConv2d(4*channel, 4*channel, 3, padding=1)
        self.conv5 = nn.Conv2d(4*channel, 1, 1)

        self.convg2_1 = BasicConv2d(2*channel, 2*channel, 3, padding=1)
        self.convg2_2 = nn.Conv2d(2*channel, 1, 1)
        self.convg3_1 = BasicConv2d(3*channel, 3*channel, 3, padding=1)
        self.convg3_2 = nn.Conv2d(3*channel, 1, 1)

        # self.conv2_f = BasicConv2d(2*channel, channel, 3, padding=1)
        # self.conv3_f = BasicConv2d(3*channel, channel, 3, padding=1)
        # self.conv4_f = BasicConv2d(4*channel, channel, 3, padding=1)

    def forward(self, x1, x2, x3,x4):
        x1_1 = x1
        x2_1 = self.conv_upsample1(self.upsample(x1_1)) * x2
        x3_1 = self.conv_upsample2_1(self.upsample(x2_1)) * self.conv_upsample2(self.upsample(x2)) * x3
        x4_1 = self.conv_upsample3_1(self.upsample(x3_1)) * self.conv_upsample3(self.upsample(x3)) * x4


        x2_2 = torch.cat((x2_1, self.conv_upsample4(self.upsample(x1_1))), 1)  #channel+channel
        x2_2 = self.conv_concat2(x2_2) #18,64,22,22
        # x2_2_conv = self.conv2_f(x2_2)

        g2_1 = self.convg2_1(x2_2)
        g2_2 = self.convg2_2(g2_1) #18,1,22,22

        x3_2 = torch.cat((x3_1, self.conv_upsample5(self.upsample(x2_2))), 1)  #2channel+channel
        x3_2 = self.conv_concat3(x3_2) #18,96,44,44
        # x3_2_conv = self.conv3_f(x3_2)

        g3_1 = self.convg3_1(x3_2)
        g3_2 = self.convg3_2(g3_1) #18,1,44,44


        x4_2 = torch.cat((x4_1, self.conv_upsample6(self.upsample(x3_2))), 1)  #3channel+channel
        x4_2 = self.conv_concat4(x4_2) #18,128,88,88
        # x4_2_conv = self.conv4_f(x4_2)

        x = self.conv4(x4_2)
        x = self.conv5(x)


        return g2_2,g3_2,x

# Group-Reversal Attention (GRA) Block
class GRA(nn.Module):
    def __init__(self, channel, subchannel):
        super(GRA, self).__init__()
        self.group = channel//subchannel
        self.conv = nn.Sequential(
            nn.Conv2d(channel + self.group, channel, 3, padding=1), nn.ReLU(True),
        )
        self.score = nn.Conv2d(channel, 1, 3, padding=1)

    def forward(self, x, y):
        if self.group == 1:
            x_cat = torch.cat((x, y), 1)
        elif self.group == 2:
            xs = torch.chunk(x, 2, dim=1)
            x_cat = torch.cat((xs[0], y, xs[1], y), 1)
        elif self.group == 4:
            xs = torch.chunk(x, 4, dim=1)
            x_cat = torch.cat((xs[0], y, xs[1], y, xs[2], y, xs[3], y), 1)
        elif self.group == 8:
            xs = torch.chunk(x, 8, dim=1)
            x_cat = torch.cat((xs[0], y, xs[1], y, xs[2], y, xs[3], y, xs[4], y, xs[5], y, xs[6], y, xs[7], y), 1)
        elif self.group == 16:
            xs = torch.chunk(x, 16, dim=1)
            x_cat = torch.cat((xs[0], y, xs[1], y, xs[2], y, xs[3], y, xs[4], y, xs[5], y, xs[6], y, xs[7], y,
            xs[8], y, xs[9], y, xs[10], y, xs[11], y, xs[12], y, xs[13], y, xs[14], y, xs[15], y), 1)
        elif self.group == 32:
            xs = torch.chunk(x, 32, dim=1)
            x_cat = torch.cat((xs[0], y, xs[1], y, xs[2], y, xs[3], y, xs[4], y, xs[5], y, xs[6], y, xs[7], y,
            xs[8], y, xs[9], y, xs[10], y, xs[11], y, xs[12], y, xs[13], y, xs[14], y, xs[15], y,
            xs[16], y, xs[17], y, xs[18], y, xs[19], y, xs[20], y, xs[21], y, xs[22], y, xs[23], y,
            xs[24], y, xs[25], y, xs[26], y, xs[27], y, xs[28], y, xs[29], y, xs[30], y, xs[31], y), 1)
        else:
            raise Exception("Invalid Channel")

        x = x + self.conv(x_cat)
        y = y + self.score(x)

        return x, y


class ReverseStage(nn.Module):
    def __init__(self, channel):
        super(ReverseStage, self).__init__()
        self.weak_gra = GRA(channel, channel)
        self.medium_gra = GRA(channel, 8)
        self.strong_gra = GRA(channel, 1)

    def forward(self, x, y):
        # reverse guided block
        #vis y and z
        y = -1 * (torch.sigmoid(y)) + 1
        # three group-reversal attention blocks
        x, y = self.weak_gra(x, y)
        x, y = self.medium_gra(x, y)
        _, y = self.strong_gra(x, y)

        return y

class NewReverseStage(nn.Module):
    def __init__(self, channel):
        super(NewReverseStage, self).__init__()
        self.weak_gra = GRA(channel, channel)
        self.medium_gra = GRA(channel, 8)
        self.strong_gra = GRA(channel, 1)

    def forward(self, x, y):
        # reverse guided block
        y = torch.sigmoid(y)
        # three group-reversal attention blocks
        x, y = self.weak_gra(x, y)
        x, y = self.medium_gra(x, y)
        _, y = self.strong_gra(x, y)

        return y
class Network(nn.Module):
    # res2net based encoder decoder
    def __init__(self, channel=32, imagenet_pretrained=True):
        super(Network, self).__init__()
        # ---- ResNet Backbone ----
        # self.resnet = res2net50_v1b_26w_4s(pretrained=imagenet_pretrained)
        self.convnext = convnext_tiny(pretrained=imagenet_pretrained)
        # ---- Receptive Field Block like module ----
        self.rfb1_1 = RFB_modified(96, channel)
        self.rfb2_1 = RFB_modified(192, channel)
        self.rfb3_1 = RFB_modified(384, channel)
        self.rfb4_1 = RFB_modified(768, channel)
        # ---- Partial Decoder ----
        self.NCD = NeighborConnectionDecoder(channel)
        # self.EDD = EdgeDecoder()
        self.EDD2 = EdgeDecoder2(channel)
        self.SRD = SurroundDecoder(channel)
                    
        # # ---- reverse stage ----
        self.RS5 = ReverseStage(channel)
        self.RS4 = ReverseStage(channel)
        self.RS3 = ReverseStage(channel)
        self.RS2 = ReverseStage(channel)

        self.NewRS5 = NewReverseStage(channel)
        self.NewRS4 = NewReverseStage(channel)
        self.NewRS3 = NewReverseStage(channel)
        self.NewRS2 = NewReverseStage(channel)
        self.conv_concat3 = BasicConv2d(2*channel, channel, 3, padding=1)
        self.conv_concat2 = BasicConv2d(2*channel, channel, 3, padding=1)
        self.conv_concat1 = BasicConv2d(2*channel, channel, 3, padding=1)

    def forward(self, x):
        # Feature Extraction
        img=x
        x1 = self.convnext.downsample_layers[0](x)
        x1 = self.convnext.stages[0](x1)            # bs, 96/128, 88, 88
        x2 = self.convnext.downsample_layers[1](x1)
        x2 = self.convnext.stages[1](x2)            # bs, 192/256, 44, 44
        x3 = self.convnext.downsample_layers[2](x2)
        x3 = self.convnext.stages[2](x3)            # bs, 384/1024, 22, 22
        x4 = self.convnext.downsample_layers[3](x3)
        x4 = self.convnext.stages[3](x4)            # bs, 768/2048, 11, 11

        # Receptive Field Block (enhanced)
        x1_rfb = self.rfb1_1(x1)        # channel -> 32
        x2_rfb = self.rfb2_1(x2)        # channel -> 32
        x3_rfb = self.rfb3_1(x3)        # channel -> 32
        x4_rfb = self.rfb4_1(x4)        # channel -> 32

        # Multi-task
        S_g = self.NCD(x4_rfb, x3_rfb, x2_rfb,x1_rfb)
        S_g_pred = F.interpolate(S_g, scale_factor=4, mode='bilinear')    # Sup-1 (bs, 1, 88, 88) -> (bs, 1, 352, 352)

        F3_edge,F2_edge,F1_edge,S_edge = self.EDD2(x4_rfb, x3_rfb, x2_rfb,x1_rfb)
        S_edge_pred = F.interpolate(S_edge, scale_factor=4, mode='bilinear')    # Sup-1 (bs, 1, 88, 88) -> (bs, 1, 352, 352)

        g3_sur,g2_sur,S_sur = self.SRD(x4_rfb, x3_rfb, x2_rfb,x1_rfb)
        g3_sur_pred = F.interpolate(g3_sur, scale_factor=16, mode='bilinear')    # Sup-1 (bs, 1, 22, 22) -> (bs, 1, 352, 352)
        g2_sur_pred = F.interpolate(g2_sur, scale_factor=8, mode='bilinear')    # Sup-1 (bs, 1, 44, 44) -> (bs, 1, 352, 352)
        S_sur_pred = F.interpolate(S_sur, scale_factor=4, mode='bilinear')    # Sup-1 (bs, 1, 88, 88) -> (bs, 1, 352, 352)

        # ---- reverse stage 5 ----
        guidance_g = F.interpolate(S_g, scale_factor=0.125, mode='bilinear')
        guidance_s = F.interpolate(S_sur, scale_factor=0.125, mode='bilinear')
        ra4_feat_g = self.RS5(x4_rfb, guidance_g)
        ra4_feat_s = self.NewRS5(x4_rfb, guidance_s)
        S_5 = guidance_g + ra4_feat_g - ra4_feat_s 
        S_5_pred = F.interpolate(S_5, scale_factor=32, mode='bilinear')  # Sup-2 (bs, 1, 11, 11) -> (bs, 1, 352, 352)

        # ---- reverse stage 4 ----
        guidance_5 = F.interpolate(S_5, scale_factor=2, mode='bilinear')
        # guidance_5 = F.interpolate(guidance_s, scale_factor=2, mode='bilinear')
        
        x3_rfb_ = torch.cat((x3_rfb,F3_edge), 1)   #32+32
        x3_rfb_ = self.conv_concat3(x3_rfb_)

        ra3_feat_g = self.RS4(x3_rfb_, guidance_5)
        ra3_feat_s = self.NewRS4(x3_rfb_, g3_sur)
        S_4 = guidance_5 + ra3_feat_g - ra3_feat_s
        S_4_pred = F.interpolate(S_4, scale_factor=16, mode='bilinear')  # Sup-3 (bs, 1, 22, 22) -> (bs, 1, 352, 352)

        # ---- reverse stage 3 ----
        guidance_4 = F.interpolate(S_4, scale_factor=2, mode='bilinear')
        # guidance_s4 = F.interpolate(guidance_s, scale_factor=4, mode='bilinear')

        x2_rfb_ = torch.cat((x2_rfb,F2_edge), 1)   #32+32
        x2_rfb_ = self.conv_concat2(x2_rfb_)

        ra2_feat_g = self.RS3(x2_rfb_, guidance_4)
        ra2_feat_s = self.NewRS3(x2_rfb_, g2_sur)
        S_3 = guidance_4 + ra2_feat_g- ra2_feat_s
        S_3_pred = F.interpolate(S_3, scale_factor=8, mode='bilinear')   # Sup-4 (bs, 1, 44, 44) -> (bs, 1, 352, 352)

        # ---- reverse stage 4 ----
        guidance_3 = F.interpolate(S_3, scale_factor=2, mode='bilinear')
        # guidance_s3 = F.interpolate(guidance_s, scale_factor=8, mode='bilinear')
    
        x1_rfb_ = torch.cat((x1_rfb,F1_edge), 1)   #32+32
        x1_rfb_ = self.conv_concat1(x1_rfb_)        
        
        ra1_feat_g = self.RS2(x1_rfb_, guidance_3)
        ra1_feat_s = self.NewRS2(x1_rfb_, S_sur)
        S_2 = guidance_3 + ra1_feat_g - ra1_feat_s
        S_2_pred = F.interpolate(S_2, scale_factor=4, mode='bilinear')   # Sup-4 (bs, 1, 88, 88) -> (bs, 1, 352, 352)

        # diyplot_db(img,S_g_pred,S_edge_pred,S_sur_pred,                            # (bs, 1, 352, 352)
        #             guidance_g,guidance_s,ra4_feat_g,ra4_feat_s,S_5_pred,          # (bs, 1, 11/11/11/11/352, 11/11/11/11/352)
        #             guidance_5,g3_sur,ra3_feat_g,ra3_feat_s,S_4_pred,              # (bs, 1, 22/22/22/22/352, 22/22/22/22/352)
        #             guidance_4,g2_sur,ra2_feat_g,ra2_feat_s,S_3_pred,              # (bs, 1, 44/44/44/44/352, 44/44/44/44/352)
        #             guidance_3,S_sur,ra1_feat_g,ra1_feat_s,S_2_pred)               # (bs, 1, 88/88/88/88/352, 88/88/88/88/352)

        return S_g_pred, S_5_pred, S_4_pred, S_3_pred,S_2_pred,S_edge_pred,S_sur_pred,g3_sur_pred,g2_sur_pred,x3,x2,x1


if __name__ == '__main__':
    import numpy as np
    from time import time
    net = Network(imagenet_pretrained=False)
    net.eval()

    dump_x = torch.randn(1, 3, 352, 352)
    frame_rate = np.zeros((1000, 1))
    for i in range(1000):
        start = time()
        y = net(dump_x)
        end = time()
        running_frame_rate = 1 * float(1 / (end - start))
        print(i, '->', running_frame_rate)
        frame_rate[i] = running_frame_rate
    print(np.mean(frame_rate))
    print(y.shape)