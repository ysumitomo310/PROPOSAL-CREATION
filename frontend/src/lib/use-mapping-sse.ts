"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getMappingStreamUrl, type MappingResultItem } from "@/lib/api";

/**
 * SSE クライアント Hook（TASK-E05）
 *
 * EventSource API で SSE 接続し、マッピング結果をリアルタイムに受信。
 */

interface UseMappingSSEReturn {
  results: MappingResultItem[];
  completedCount: number;
  totalCount: number;
  errorCount: number;
  isComplete: boolean;
  errors: string[];
  connect: () => void;
  disconnect: () => void;
}

export function useMappingSSE(caseId: string): UseMappingSSEReturn {
  const [results, setResults] = useState<MappingResultItem[]>([]);
  const [completedCount, setCompletedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [errorCount, setErrorCount] = useState(0);
  const [isComplete, setIsComplete] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);
  const esRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (esRef.current) return;

    const url = getMappingStreamUrl(caseId);
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("requirement_complete", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setResults((prev) => [...prev, data as MappingResultItem]);
      setCompletedCount(data.completed_count ?? 0);
      setTotalCount(data.total_count ?? 0);
    });

    es.addEventListener("progress", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setCompletedCount(data.completed_count ?? 0);
      setTotalCount(data.total_count ?? 0);
    });

    es.addEventListener("batch_complete", (e: MessageEvent) => {
      const data = JSON.parse(e.data);
      setIsComplete(true);
      setCompletedCount(data.completed ?? 0);
      setTotalCount(data.total ?? 0);
      setErrorCount(data.errors ?? 0);
      es.close();
      esRef.current = null;
    });

    es.addEventListener("error", (e: Event) => {
      if (e instanceof MessageEvent) {
        const data = JSON.parse(e.data);
        setErrors((prev) => [...prev, data.error]);
        setErrorCount((prev) => prev + 1);
      }
    });
  }, [caseId]);

  const disconnect = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
  }, []);

  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  return {
    results,
    completedCount,
    totalCount,
    errorCount,
    isComplete,
    errors,
    connect,
    disconnect,
  };
}
