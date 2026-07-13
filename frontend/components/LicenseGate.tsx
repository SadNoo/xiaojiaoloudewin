import React, { useState } from 'react';
import { AlertTriangle, Download, KeyRound, Loader2, Monitor, RefreshCw, ShieldCheck, WifiOff } from 'lucide-react';
import type { LicenseStatus } from '../types';

interface LicenseGateProps {
  status: LicenseStatus;
  loading: boolean;
  error: string;
  onActivate: (licenseCode: string) => Promise<void>;
  onRetry: () => Promise<void>;
}

const formatDate = (value?: string | null) => {
  if (!value) return '无限期';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN');
};

const LicenseGate: React.FC<LicenseGateProps> = ({ status, loading, error, onActivate, onRetry }) => {
  const [licenseCode, setLicenseCode] = useState('');
  const updateRequired = status.state === 'update_required';
  const configurationError = !status.initialized;
  const Icon = updateRequired ? Download : configurationError ? AlertTriangle : status.reason_code === 'server_unreachable' ? WifiOff : KeyRound;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (licenseCode.trim()) await onActivate(licenseCode.trim());
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F4F5F7] p-4 relative overflow-hidden font-sans">
      <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] bg-yellow-200/40 rounded-full blur-[120px]"></div>
      <div className="absolute bottom-[-10%] right-[-10%] w-[60%] h-[60%] bg-blue-200/30 rounded-full blur-[120px]"></div>

      <div className="bg-white/85 backdrop-blur-3xl p-8 md:p-12 rounded-[3rem] shadow-[0_20px_60px_-15px_rgba(0,0,0,0.08)] w-full max-w-xl border border-white relative z-10">
        <div className="text-center mb-8">
          <div className="w-24 h-24 bg-[#FFE815] rounded-[2rem] flex items-center justify-center shadow-xl shadow-yellow-200 mx-auto mb-6 -rotate-3">
            <Icon className="w-11 h-11 text-black" />
          </div>
          <h2 className="text-3xl font-extrabold text-gray-900 mb-2 tracking-tight">
            {updateRequired ? '需要更新客户端' : configurationError ? '授权模块尚未配置' : '激活这台设备'}
          </h2>
          <p className="text-gray-600 font-medium leading-relaxed">{status.message}</p>
        </div>

        <div className="grid grid-cols-2 gap-3 mb-6">
          <div className="p-4 rounded-2xl bg-gray-50 border border-gray-100">
            <div className="text-xs text-gray-400 mb-1 flex items-center gap-1"><Monitor className="w-3.5 h-3.5" /> 当前设备</div>
            <div className="font-bold text-sm truncate">{status.device_name || '等待初始化'}</div>
          </div>
          <div className="p-4 rounded-2xl bg-gray-50 border border-gray-100">
            <div className="text-xs text-gray-400 mb-1">授权到期</div>
            <div className="font-bold text-sm truncate">{formatDate(status.license_expires_at)}</div>
          </div>
        </div>

        {updateRequired && (
          <div className="p-4 rounded-2xl bg-amber-50 border border-amber-100 mb-5 text-sm text-amber-800 space-y-3">
            <div>当前版本低于最低允许版本 <b>{status.minimum_version || '未知'}</b>，最新版本为 <b>{status.latest_version || '未知'}</b>。更新完成后重新验证。</div>
            {status.download_url && (
              <a href={status.download_url} className="h-11 px-4 rounded-xl bg-amber-900 text-white font-bold flex items-center justify-center gap-2">
                <Download className="w-4 h-4" /> 下载最新版安装包
              </a>
            )}
          </div>
        )}

        {configurationError && (
          <div className="p-4 rounded-2xl bg-red-50 border border-red-100 mb-5 text-sm text-red-700 break-words">
            {status.initialization_error || '请在 Windows 构建配置中写入授权 API 地址和 Ed25519 公钥。'}
          </div>
        )}

        {!updateRequired && !configurationError && (
          <form onSubmit={submit} className="space-y-4">
            <div className="relative">
              <KeyRound className="absolute left-5 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                value={licenseCode}
                onChange={(event) => setLicenseCode(event.target.value.toUpperCase())}
                placeholder="XY-XXXXX-XXXXX-XXXXX-XXXXX-XXXXX"
                autoComplete="off"
                spellCheck={false}
                className="w-full ios-input pl-14 pr-5 h-14 rounded-2xl font-mono tracking-wide"
              />
            </div>
            <button disabled={loading || licenseCode.trim().length < 20} className="w-full ios-btn-primary h-14 rounded-2xl text-lg shadow-xl shadow-yellow-200 flex items-center justify-center gap-2 disabled:opacity-60">
              {loading ? <Loader2 className="w-5 h-5 animate-spin" /> : <><ShieldCheck className="w-5 h-5" /> 联网激活</>}
            </button>
          </form>
        )}

        {error && <div className="mt-4 p-3 rounded-xl bg-red-50 text-red-600 text-sm text-center font-bold">{error}</div>}

        <button
          type="button"
          disabled={loading}
          onClick={onRetry}
          className="w-full mt-4 h-12 rounded-2xl text-gray-600 hover:bg-gray-50 transition flex items-center justify-center gap-2 font-semibold disabled:opacity-60"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> 重新联网验证
        </button>

        <div className="mt-6 pt-5 border-t border-gray-100 text-center text-xs text-gray-400">
          首次激活必须联网 · 一个授权码仅绑定一台设备 · 临时断网最多宽限 72 小时
        </div>
      </div>
    </div>
  );
};

export default LicenseGate;
