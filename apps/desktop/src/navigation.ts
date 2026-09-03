/* Rail de navegacion y textos de cada pagina, en un solo sitio. */

import {
  Archive,
  BarChart3,
  ClipboardCheck,
  Cpu,
  Database,
  FlaskConical,
  FolderOpen,
  ListChecks,
  ScrollText,
  Settings,
  Target,
  type LucideIcon,
} from "lucide-react";

export const navigation: { group: string; label: string; icon: LucideIcon }[] = [
  { group: "Misión actual", label: "Misiones", icon: Target },
  { group: "Misión actual", label: "Planes y borradores", icon: ListChecks },
  { group: "Misión actual", label: "Evidencia", icon: Archive },
  { group: "Misión actual", label: "Recursos", icon: FolderOpen },
  { group: "Ejecución", label: "Experimentos", icon: FlaskConical },
  { group: "Ejecución", label: "Revisiones", icon: ClipboardCheck },
  { group: "Ejecución", label: "Datasets", icon: Database },
  { group: "Ejecución", label: "Entrenamientos", icon: Cpu },
  { group: "Observabilidad", label: "Registros", icon: ScrollText },
  { group: "Observabilidad", label: "Métricas", icon: BarChart3 },
  { group: "Configuración", label: "Configuración", icon: Settings },
];

export const pageCopy: Record<string, { title: string; description: string }> = {
  Misiones: { title: "Quiero entrenar un modelo", description: "Elige una estrategia y construye un plan guiado de principio a fin." },
  "Planes y borradores": { title: "Planes y borradores", description: "Retoma recorridos, revisa resultados y continúa desde el último paso seguro." },
  Evidencia: { title: "Mesa de evidencia", description: "Lo probado, lo detectado y lo que todavía impide avanzar." },
  Recursos: { title: "Recursos del laboratorio", description: "Vaults, snapshots, índices y equipos disponibles para tus misiones." },
  Experimentos: { title: "Ensayos comparables", description: "Benchmarks y estrategias sobre la misma suite, snapshot y conjunto de casos." },
  Revisiones: { title: "Revisión humana", description: "Correcciones, diferencias y evidencia antes de aprobar cualquier dato de entrenamiento." },
  Datasets: { title: "Fábrica de datasets", description: "Ejemplos aprobados, deduplicados y aislados de todos los benchmarks." },
  Entrenamientos: { title: "Entrenamiento y exportación", description: "Pruebas cortas, trabajos recuperables y paquetes verificables." },
  Registros: { title: "Actividad del laboratorio", description: "Sigue cada trabajo desde la interfaz hasta el Worker y sus dependencias externas." },
  Métricas: { title: "Métricas por configuración", description: "Compara resultados exactos sin convertir una observación en una superioridad general." },
  Configuración: { title: "Entorno y dependencias", description: "Comprueba integraciones sin modificar sistemas externos ni persistir secretos." },
};
