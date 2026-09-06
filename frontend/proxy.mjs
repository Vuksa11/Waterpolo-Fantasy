// Trust only the direct peer. Never forward a browser-supplied client identity.
export function proxyHeaders(headers, remoteAddress, host) {
  const result = { ...headers, host };
  delete result.forwarded;
  delete result["x-real-ip"];
  result["x-forwarded-for"] = (remoteAddress || "unknown").replace(
    /^::ffff:/,
    "",
  );
  return result;
}
