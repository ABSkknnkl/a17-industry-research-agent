/**
 * 视频规格常量定义
 * 16:9 横屏 1080P，30FPS
 */

export const VIDEO_FPS = 30;
export const VIDEO_WIDTH = 1920;
export const VIDEO_HEIGHT = 1080;

// 时长定义 (秒 ➔ 帧数)
export const OVERVIEW_DURATION_IN_FRAMES = 35 * VIDEO_FPS; // 1050 帧 (35秒)
export const AGENT_DURATION_IN_FRAMES = 20 * VIDEO_FPS;    // 600 帧 (20秒)
