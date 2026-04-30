export default function Loading() {
  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center space-y-4">
      <div className="w-12 h-12 border-4 border-blue-600/20 border-t-blue-600 rounded-full animate-spin"></div>
      <p className="text-sm font-bold text-blue-600 tracking-widest uppercase animate-pulse">
        AIcreator Loading...
      </p>
    </div>
  );
}
