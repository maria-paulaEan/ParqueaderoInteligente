"""
SIMULADOR DE PARQUEADERO INTELIGENTE
Universidad EAN – Arquitectura de Computadores y Sistemas Operativos
Docente: Diana Carolina Beltrán Peña
Año: 2025
"""

import tkinter as tk
from tkinter import ttk, font
import threading
import time
import random
import queue
from datetime import datetime

# ──────────────────────────────────────────────
# CONFIGURACIÓN GLOBAL
# ──────────────────────────────────────────────
random.seed(42)                  # Reproducibilidad
CAPACIDAD       = 6              # Espacios totales del parqueadero
TIEMPO_MIN      = 2              # Tiempo mínimo estacionado (segundos)
TIEMPO_MAX      = 8              # Tiempo máximo estacionado (segundos)
ESPERA_LLEGADA  = (1, 4)         # Rango de tiempo antes de llegar

# ──────────────────────────────────────────────
# VARIABLES COMPARTIDAS (sección crítica)
# ──────────────────────────────────────────────
semaforo        = threading.Semaphore(CAPACIDAD)   # Controla cupos disponibles
lock            = threading.Lock()                 # Protege variables compartidas
ocupados        = 0                                # Espacios actualmente ocupados
vehiculo_id     = 0                                # Contador global de vehículos
simulacion_activa = False                          # Flag de control
evento_parar    = threading.Event()                # Señal para detener hilos

# Cola para comunicar hilos con la UI (Tkinter solo se actualiza en hilo principal)
cola_eventos = queue.Queue()

# Registro de métricas
tiempos_espera  = []
log_eventos     = []


# ──────────────────────────────────────────────
# FUNCIÓN HILO – VEHÍCULO
# ──────────────────────────────────────────────
def hilo_vehiculo(vid: int, cola: queue.Queue):
    """
    Representa un vehículo (proceso) que:
    1. Espera antes de llegar
    2. Solicita acceso al semáforo (espera si está lleno)
    3. Se estaciona un tiempo aleatorio
    4. Libera el espacio y sale
    """
    global ocupados

    nombre = f"Vehículo {vid:03d}"

    # ── 1. LLEGADA ──
    tiempo_llegada = random.uniform(*ESPERA_LLEGADA)
    cola.put(("estado", vid, "llegando", f"{nombre} se acerca... (llega en {tiempo_llegada:.1f}s)"))
    time.sleep(tiempo_llegada)

    if evento_parar.is_set():
        cola.put(("estado", vid, "retirado", f"{nombre} se retiró (simulación detenida)"))
        cola.put(("terminar", vid))
        return

    # ── 2. SOLICITAR CUPO (Semáforo) ──
    cola.put(("estado", vid, "esperando", f"{nombre} esperando cupo..."))
    t_inicio_espera = time.time()

    # acquire(timeout) evita bloqueo infinito si se detiene la simulación
    while not evento_parar.is_set():
        adquirido = semaforo.acquire(timeout=0.5)
        if adquirido:
            break
    else:
        cola.put(("estado", vid, "retirado", f"{nombre} se retiró (simulación detenida)"))
        cola.put(("terminar", vid))
        return

    t_espera = time.time() - t_inicio_espera

    # ── 3. ENTRAR AL PARQUEADERO (Lock protege 'ocupados') ──
    with lock:
        ocupados += 1
        tiempos_espera.append(t_espera)
        espacio_num = ocupados

    cola.put(("estado", vid, "estacionado",
              f"{nombre} ingresó → Espacio #{espacio_num} | Esperó {t_espera:.1f}s"))
    cola.put(("actualizar_spaces",))

    # ── 4. PERMANECER ESTACIONADO ──
    tiempo_estacionado = random.uniform(TIEMPO_MIN, TIEMPO_MAX)
    time.sleep(tiempo_estacionado)

    if evento_parar.is_set():
        # Liberar aunque se haya detenido
        with lock:
            ocupados -= 1
        semaforo.release()
        cola.put(("estado", vid, "retirado", f"{nombre} salió (simulación detenida)"))
        cola.put(("actualizar_spaces",))
        cola.put(("terminar", vid))
        return

    # ── 5. SALIR Y LIBERAR (Lock + Semaphore.release) ──
    with lock:
        ocupados -= 1

    semaforo.release()   # Libera el cupo → otro vehículo puede entrar

    cola.put(("estado", vid, "salio",
              f"{nombre} salió ✓ | Estuvo {tiempo_estacionado:.1f}s estacionado"))
    cola.put(("actualizar_spaces",))
    cola.put(("terminar", vid))


# ──────────────────────────────────────────────
# INTERFAZ GRÁFICA – TKINTER
# ──────────────────────────────────────────────
class SimuladorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("🚗 Parqueadero Inteligente – Simulador SO")
        self.root.configure(bg="#0f1117")
        self.root.geometry("960x720")
        self.root.resizable(True, True)

        self.vehiculos_activos = {}   # vid → {"frame": ..., "label_estado": ...}
        self._construir_ui()
        self._procesar_cola()         # Loop de actualización UI cada 100ms

    # ── CONSTRUCCIÓN DE LA UI ──────────────────
    def _construir_ui(self):
        # ── Título ──
        header = tk.Frame(self.root, bg="#0f1117")
        header.pack(fill="x", padx=20, pady=(18, 4))

        tk.Label(header, text="PARQUEADERO INTELIGENTE",
                 font=("Courier New", 22, "bold"),
                 fg="#00e5ff", bg="#0f1117").pack(side="left")

        tk.Label(header, text="Simulador de SO · Universidad EAN",
                 font=("Courier New", 10),
                 fg="#4a5568", bg="#0f1117").pack(side="right", pady=8)

        # ── Separador ──
        tk.Frame(self.root, bg="#00e5ff", height=1).pack(fill="x", padx=20)

        # ── Panel superior: espacios + métricas ──
        top = tk.Frame(self.root, bg="#0f1117")
        top.pack(fill="x", padx=20, pady=12)

        # Panel de espacios visuales
        self._panel_espacios(top)

        # Panel de métricas
        self._panel_metricas(top)

        # ── Botones de control ──
        self._panel_botones()

        # ── Lista de vehículos ──
        tk.Label(self.root, text="▸ ACTIVIDAD DE VEHÍCULOS",
                 font=("Courier New", 11, "bold"),
                 fg="#a0aec0", bg="#0f1117").pack(anchor="w", padx=22, pady=(6, 2))

        self.frame_vehiculos = tk.Frame(self.root, bg="#0f1117")
        self.frame_vehiculos.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        # Scroll
        canvas = tk.Canvas(self.frame_vehiculos, bg="#0f1117",
                           highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.frame_vehiculos,
                                  orient="vertical", command=canvas.yview)
        self.scroll_frame = tk.Frame(canvas, bg="#0f1117")
        self.scroll_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # ── Log inferior ──
        tk.Label(self.root, text="▸ LOG DEL SISTEMA",
                 font=("Courier New", 11, "bold"),
                 fg="#a0aec0", bg="#0f1117").pack(anchor="w", padx=22, pady=(2, 2))

        self.log_text = tk.Text(self.root, height=5,
                                bg="#1a1d27", fg="#68d391",
                                font=("Courier New", 9),
                                relief="flat", state="disabled",
                                insertbackground="#00e5ff")
        self.log_text.pack(fill="x", padx=20, pady=(0, 12))

    def _panel_espacios(self, parent):
        frame = tk.Frame(parent, bg="#161b2e",
                         highlightbackground="#1e2a45",
                         highlightthickness=1)
        frame.pack(side="left", padx=(0, 12), pady=4, fill="y")

        tk.Label(frame, text="ESPACIOS DEL PARQUEADERO",
                 font=("Courier New", 9, "bold"),
                 fg="#4a5568", bg="#161b2e").pack(pady=(8, 4), padx=16)

        self.frame_celdas = tk.Frame(frame, bg="#161b2e")
        self.frame_celdas.pack(padx=16, pady=(0, 10))

        self.celdas = []
        for i in range(CAPACIDAD):
            celda = tk.Label(self.frame_celdas,
                             text=f"P{i+1}\n🟢",
                             font=("Courier New", 12),
                             bg="#0d2137", fg="#68d391",
                             width=5, height=2,
                             relief="flat",
                             highlightbackground="#1e3a5f",
                             highlightthickness=1)
            celda.grid(row=i//3, column=i%3, padx=3, pady=3)
            self.celdas.append(celda)

        # Contador grande
        self.lbl_ocupados = tk.Label(frame,
                                     text=f"0 / {CAPACIDAD}",
                                     font=("Courier New", 20, "bold"),
                                     fg="#00e5ff", bg="#161b2e")
        self.lbl_ocupados.pack(pady=(4, 8))

        tk.Label(frame, text="ocupados / total",
                 font=("Courier New", 8),
                 fg="#4a5568", bg="#161b2e").pack(pady=(0, 8))

    def _panel_metricas(self, parent):
        frame = tk.Frame(parent, bg="#161b2e",
                         highlightbackground="#1e2a45",
                         highlightthickness=1)
        frame.pack(side="left", fill="both", expand=True, pady=4)

        tk.Label(frame, text="MÉTRICAS EN TIEMPO REAL",
                 font=("Courier New", 9, "bold"),
                 fg="#4a5568", bg="#161b2e").pack(pady=(8, 6), padx=16, anchor="w")

        metricas_frame = tk.Frame(frame, bg="#161b2e")
        metricas_frame.pack(fill="x", padx=16)

        def metrica(parent, titulo, var_name, color):
            f = tk.Frame(parent, bg="#161b2e")
            f.pack(fill="x", pady=3)
            tk.Label(f, text=titulo,
                     font=("Courier New", 9),
                     fg="#718096", bg="#161b2e", width=26, anchor="w").pack(side="left")
            lbl = tk.Label(f, text="—",
                           font=("Courier New", 11, "bold"),
                           fg=color, bg="#161b2e")
            lbl.pack(side="left")
            setattr(self, var_name, lbl)

        metrica(metricas_frame, "Total vehículos procesados:", "lbl_total",    "#00e5ff")
        metrica(metricas_frame, "Actualmente esperando:",      "lbl_esperando","#f6ad55")
        metrica(metricas_frame, "Tiempo promedio de espera:",  "lbl_prom",     "#68d391")
        metrica(metricas_frame, "Utilización del recurso:",    "lbl_util",     "#fc8181")
        metrica(metricas_frame, "Hilos activos:",              "lbl_hilos",    "#b794f4")

        # Barra de utilización
        tk.Label(frame, text="UTILIZACIÓN",
                 font=("Courier New", 8),
                 fg="#4a5568", bg="#161b2e").pack(anchor="w", padx=16, pady=(8, 2))

        self.canvas_barra = tk.Canvas(frame, height=16,
                                      bg="#0d1117", highlightthickness=0)
        self.canvas_barra.pack(fill="x", padx=16, pady=(0, 12))

    def _panel_botones(self):
        frame = tk.Frame(self.root, bg="#0f1117")
        frame.pack(fill="x", padx=20, pady=(0, 8))

        btn_style = {
            "font": ("Courier New", 10, "bold"),
            "relief": "flat", "padx": 18, "pady": 8,
            "cursor": "hand2"
        }

        self.btn_iniciar = tk.Button(frame,
            text="▶  INICIAR SIMULACIÓN",
            bg="#00e5ff", fg="#0f1117",
            command=self.iniciar_simulacion, **btn_style)
        self.btn_iniciar.pack(side="left", padx=(0, 8))

        self.btn_agregar = tk.Button(frame,
            text="＋  AGREGAR VEHÍCULO",
            bg="#68d391", fg="#0f1117",
            command=self.agregar_vehiculo_manual,
            state="disabled", **btn_style)
        self.btn_agregar.pack(side="left", padx=(0, 8))

        self.btn_detener = tk.Button(frame,
            text="⏹  DETENER",
            bg="#fc8181", fg="#0f1117",
            command=self.detener_simulacion,
            state="disabled", **btn_style)
        self.btn_detener.pack(side="left", padx=(0, 8))

        self.btn_reiniciar = tk.Button(frame,
            text="↺  REINICIAR",
            bg="#b794f4", fg="#0f1117",
            command=self.reiniciar_simulacion,
            state="disabled", **btn_style)
        self.btn_reiniciar.pack(side="left")

        # Estado del sistema
        self.lbl_sistema = tk.Label(frame,
            text="● SISTEMA DETENIDO",
            font=("Courier New", 10, "bold"),
            fg="#fc8181", bg="#0f1117")
        self.lbl_sistema.pack(side="right")

    # ── CONTROL DE SIMULACIÓN ─────────────────
    def iniciar_simulacion(self):
        global simulacion_activa, vehiculo_id
        simulacion_activa = True
        evento_parar.clear()
        vehiculo_id = 0

        self.btn_iniciar.config(state="disabled")
        self.btn_agregar.config(state="normal")
        self.btn_detener.config(state="normal")
        self.btn_reiniciar.config(state="disabled")
        self.lbl_sistema.config(text="● SISTEMA ACTIVO", fg="#68d391")

        self._log("Sistema iniciado. Parqueadero con "
                  f"{CAPACIDAD} espacios disponibles.")

        # Lanzar vehículos iniciales
        for _ in range(CAPACIDAD + 2):
            self._lanzar_vehiculo()

    def agregar_vehiculo_manual(self):
        if simulacion_activa:
            self._lanzar_vehiculo()

    def _lanzar_vehiculo(self):
        global vehiculo_id
        with lock:
            vehiculo_id += 1
            vid = vehiculo_id

        # Crear fila en la UI para este vehículo
        self._crear_fila_vehiculo(vid)

        # Lanzar hilo
        t = threading.Thread(target=hilo_vehiculo,
                             args=(vid, cola_eventos),
                             daemon=True,
                             name=f"Vehiculo-{vid:03d}")
        t.start()

    def detener_simulacion(self):
        global simulacion_activa
        simulacion_activa = False
        evento_parar.set()

        self.btn_agregar.config(state="disabled")
        self.btn_detener.config(state="disabled")
        self.btn_reiniciar.config(state="normal")
        self.lbl_sistema.config(text="● SISTEMA DETENIDO", fg="#fc8181")
        self._log("Simulación detenida por el usuario.")

    def reiniciar_simulacion(self):
        global ocupados, vehiculo_id, simulacion_activa
        global semaforo, tiempos_espera, log_eventos

        # Reset variables globales
        evento_parar.clear()
        simulacion_activa = False
        ocupados = 0
        vehiculo_id = 0
        tiempos_espera.clear()
        log_eventos.clear()
        semaforo = threading.Semaphore(CAPACIDAD)

        # Limpiar UI
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.vehiculos_activos.clear()

        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

        self._actualizar_espacios_ui()
        self._actualizar_metricas_ui()

        self.btn_iniciar.config(state="normal")
        self.btn_agregar.config(state="disabled")
        self.btn_detener.config(state="disabled")
        self.btn_reiniciar.config(state="disabled")
        self.lbl_sistema.config(text="● SISTEMA DETENIDO", fg="#fc8181")
        self._log("Sistema reiniciado. Listo para nueva simulación.")

    # ── PROCESAMIENTO DE COLA (hilo principal) ─
    def _procesar_cola(self):
        """
        Loop que corre en el hilo principal cada 100ms.
        Lee eventos enviados por los hilos y actualiza la UI de forma segura.
        NUNCA actualizar widgets Tkinter desde hilos secundarios.
        """
        try:
            while True:
                evento = cola_eventos.get_nowait()

                tipo = evento[0]

                if tipo == "estado":
                    _, vid, estado, mensaje = evento
                    self._actualizar_vehiculo_ui(vid, estado, mensaje)
                    self._log(mensaje)
                    self._actualizar_metricas_ui()

                elif tipo == "actualizar_spaces":
                    self._actualizar_espacios_ui()
                    self._actualizar_metricas_ui()

                elif tipo == "terminar":
                    _, vid = evento
                    # Marcar como terminado después de 3 segundos
                    self.root.after(3000, lambda v=vid: self._eliminar_vehiculo_ui(v))

        except queue.Empty:
            pass

        # Volver a ejecutar en 100ms (Tkinter event loop)
        self.root.after(100, self._procesar_cola)

    # ── ACTUALIZACIÓN DE UI ───────────────────
    def _crear_fila_vehiculo(self, vid):
        fila = tk.Frame(self.scroll_frame,
                        bg="#161b2e",
                        highlightbackground="#1e2a45",
                        highlightthickness=1)
        fila.pack(fill="x", pady=2, padx=2)

        lbl_id = tk.Label(fila,
                          text=f"V{vid:03d}",
                          font=("Courier New", 10, "bold"),
                          fg="#00e5ff", bg="#161b2e", width=6)
        lbl_id.pack(side="left", padx=8, pady=4)

        indicador = tk.Label(fila, text="●",
                             font=("Courier New", 12),
                             fg="#f6ad55", bg="#161b2e", width=2)
        indicador.pack(side="left")

        lbl_estado = tk.Label(fila,
                              text="Llegando...",
                              font=("Courier New", 9),
                              fg="#a0aec0", bg="#161b2e",
                              anchor="w")
        lbl_estado.pack(side="left", padx=8, fill="x", expand=True)

        lbl_tiempo = tk.Label(fila,
                              text=datetime.now().strftime("%H:%M:%S"),
                              font=("Courier New", 8),
                              fg="#4a5568", bg="#161b2e")
        lbl_tiempo.pack(side="right", padx=8)

        self.vehiculos_activos[vid] = {
            "frame": fila,
            "indicador": indicador,
            "label_estado": lbl_estado,
        }

    COLORES_ESTADO = {
        "llegando":   ("#f6ad55", "Llegando..."),
        "esperando":  ("#fc8181", "⏳ Esperando cupo"),
        "estacionado":("#68d391", "🚗 Estacionado"),
        "salio":      ("#4a5568", "✓ Salió"),
        "retirado":   ("#4a5568", "✗ Retirado"),
    }

    def _actualizar_vehiculo_ui(self, vid, estado, mensaje):
        if vid not in self.vehiculos_activos:
            return
        color, texto_corto = self.COLORES_ESTADO.get(estado, ("#a0aec0", estado))
        datos = self.vehiculos_activos[vid]
        datos["indicador"].config(fg=color)
        datos["label_estado"].config(text=mensaje, fg=color)

    def _eliminar_vehiculo_ui(self, vid):
        if vid in self.vehiculos_activos:
            self.vehiculos_activos[vid]["frame"].destroy()
            del self.vehiculos_activos[vid]

    def _actualizar_espacios_ui(self):
        libre   = CAPACIDAD - ocupados
        for i, celda in enumerate(self.celdas):
            if i < ocupados:
                celda.config(text=f"P{i+1}\n🔴", fg="#fc8181", bg="#2d1515")
            else:
                celda.config(text=f"P{i+1}\n🟢", fg="#68d391", bg="#0d2137")

        self.lbl_ocupados.config(
            text=f"{ocupados} / {CAPACIDAD}",
            fg="#fc8181" if ocupados == CAPACIDAD else "#00e5ff"
        )

    def _actualizar_metricas_ui(self):
        esperando = sum(
            1 for v in self.vehiculos_activos.values()
            if "⏳" in v["label_estado"].cget("text")
               or "esperando" in v["label_estado"].cget("text").lower()
        )

        total_procesados = vehiculo_id
        prom = (sum(tiempos_espera) / len(tiempos_espera)
                if tiempos_espera else 0)
        util = (ocupados / CAPACIDAD * 100) if CAPACIDAD > 0 else 0
        hilos = threading.active_count() - 1  # descontar hilo principal

        self.lbl_total.config(text=str(total_procesados))
        self.lbl_esperando.config(text=str(esperando))
        self.lbl_prom.config(text=f"{prom:.2f}s")
        self.lbl_util.config(text=f"{util:.0f}%")
        self.lbl_hilos.config(text=str(max(0, hilos)))

        # Barra de utilización
        self.canvas_barra.update_idletasks()
        w = self.canvas_barra.winfo_width()
        self.canvas_barra.delete("all")
        color_barra = "#fc8181" if util >= 80 else "#f6ad55" if util >= 50 else "#68d391"
        if w > 10:
            self.canvas_barra.create_rectangle(
                0, 0, int(w * util / 100), 16,
                fill=color_barra, outline=""
            )

    def _log(self, mensaje):
        ts = datetime.now().strftime("%H:%M:%S")
        linea = f"[{ts}] {mensaje}\n"
        self.log_text.config(state="normal")
        self.log_text.insert("end", linea)
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        log_eventos.append(linea)


# ──────────────────────────────────────────────
# PUNTO DE ENTRADA
# ──────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()

    # Estilo ttk para el scrollbar
    style = ttk.Style()
    style.theme_use("default")
    style.configure("Vertical.TScrollbar",
                    background="#1e2a45",
                    troughcolor="#0f1117",
                    arrowcolor="#4a5568")

    app = SimuladorGUI(root)
    root.mainloop()
