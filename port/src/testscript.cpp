#include "testscript.h"

#include <fstream>
#include <map>
#include <sstream>
#include <cstdio>
#include <cstdlib>

static const std::map<std::string, int> kKeys = {
    {"A", 0}, {"B", 1}, {"SELECT", 2}, {"START", 3}, {"RIGHT", 4}, {"LEFT", 5},
    {"UP", 6}, {"DOWN", 7}, {"R", 8}, {"L", 9}, {"X", 10}, {"Y", 11}};

bool TestScript::load(const std::string& path) {
    std::ifstream f(path);
    if (!f) return false;
    std::string line;
    while (std::getline(f, line)) {
        auto h = line.find('#');
        if (h != std::string::npos) line = line.substr(0, h);
        std::istringstream ss(line);
        Cmd c;
        if (!(ss >> c.op)) continue;
        std::string a;
        while (ss >> a) c.args.push_back(a);
        cmds_.push_back(c);
    }
    return true;
}

static uint32_t keyBit(const std::string& k) {
    auto it = kKeys.find(k);
    return it == kKeys.end() ? 0 : 1u << it->second;
}

static bool near(uint32_t a, uint32_t b) {
    for (int sh = 0; sh < 24; sh += 8) {
        int d = (int)((a >> sh) & 0xFF) - (int)((b >> sh) & 0xFF);
        if (d < -12 || d > 12) return false;
    }
    return true;
}

void TestScript::frame(uint32_t& keyMask, bool& touching, int& tx, int& ty, std::vector<std::string>& shots) {
    // timed actions in progress
    if (waitingPixel_ && pulseLeft_ == 0 && releaseLeft_ == 0) {
        if (pixel && near(pixel(px_, py_), pColor_)) {
            waitingPixel_ = false;
        } else if (++pTimer_ > pTimeout_) {
            waitingPixel_ = false;
            failed_ = true;
            fprintf(stderr, "test script: timeout waiting for pixel (%d,%d)=%06x, got %06x\n", px_, py_, pColor_,
                    pixel ? pixel(px_, py_) & 0xFFFFFF : 0);
            pc_ = cmds_.size();
        } else if (pKey_ && pTimer_ % 40 == 0) {
            pulse_ = pKey_;
            pulseLeft_ = 6;
        }
    }
    if (waitingPixel_ && pulseLeft_ == 0 && releaseLeft_ == 0) {
        // keep waiting
    } else if (pulseLeft_ > 0) {
        if (--pulseLeft_ == 0) { pulse_ = 0; releaseLeft_ = 6; }
    } else if (releaseLeft_ > 0) {
        --releaseLeft_;
    } else if (touchLeft_ > 0) {
        if (--touchLeft_ == 0) { touching_ = false; releaseLeft_ = 6; }
    } else if (wait_ > 0) {
        --wait_;
    } else {
        // run instantaneous commands until one that takes time
        while (pc_ < cmds_.size()) {
            const Cmd& c = cmds_[pc_++];
            auto arg = [&](size_t i, int def) { return i < c.args.size() ? std::atoi(c.args[i].c_str()) : def; };
            if (c.op == "wait") { wait_ = arg(0, 1); break; }
            if (c.op == "press") { pulse_ = keyBit(c.args.empty() ? "" : c.args[0]); pulseLeft_ = arg(1, 6); break; }
            if (c.op == "hold") { held_ |= keyBit(c.args.empty() ? "" : c.args[0]); continue; }
            if (c.op == "release") { held_ &= ~keyBit(c.args.empty() ? "" : c.args[0]); continue; }
            if (c.op == "touch") { tx_ = arg(0, 0); ty_ = arg(1, 0); touchLeft_ = arg(2, 6); touching_ = true; break; }
            if (c.op == "shot" && !c.args.empty()) { shots.push_back(c.args[0]); continue; }
            if (c.op == "gpudump" && !c.args.empty()) { shots.push_back("gpu:" + c.args[0]); continue; }
            if ((c.op == "until" && c.args.size() >= 3) || (c.op == "pressuntil" && c.args.size() >= 4)) {
                size_t o = c.op == "until" ? 0 : 1;
                pKey_ = o ? keyBit(c.args[0]) : 0;
                px_ = std::atoi(c.args[o].c_str());
                py_ = std::atoi(c.args[o + 1].c_str());
                pColor_ = (uint32_t)strtoul(c.args[o + 2].c_str(), nullptr, 16);
                pTimeout_ = c.args.size() > o + 3 ? std::atoi(c.args[o + 3].c_str()) : 3000;
                pTimer_ = 0;
                waitingPixel_ = true;
                break;
            }
        }
    }
    keyMask = ~(held_ | pulse_) & 0xFFF;
    touching = touching_;
    tx = tx_;
    ty = ty_;
}
