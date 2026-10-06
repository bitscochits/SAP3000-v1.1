/*
================================================================
  VisorPersona.Cabina.cs  --  manejar el AT-ST desde adentro
================================================================
  V (o el boton del panel) mete la camara en la cabina del AT-ST:
  primera persona, a la altura de sus ojos, mirando hacia donde va.

      W / flecha arriba    avanza          A / flecha izq.   gira a la izq.
      S / flecha abajo     retrocede       D / flecha der.   gira a la der.
      boton derecho        mirar alrededor (la cabeza, no el AT-ST)
      Q / E                piso de abajo / de arriba
      V                    salir

  Todo lo demas sigue igual: la carga, la deformada y los momentos son
  los de donde pisa; y como la camara va con el, se siente bajar la losa
  (con la escala de dibujo). Solo es dibujo.

  La camara normal es CamaraOrbital, que la ubica en cada LateUpdate:
  mientras se maneja desde la cabina se APAGA (no basta 'bloqueada', que
  igual la reubica) y al salir vuelve con su orbita de antes. No hay
  colisiones: el AT-ST atraviesa columnas y muros.
================================================================
*/

using UnityEngine;

public partial class VisorPersona
{
    const float OJOS_ALTURA_M = 2.30f;     // la cabina del AT-ST de 2.8 m
    const float OJOS_ADELANTE_M = 0.30f;
    const float GIRO_GRADOS_S = 90f;
    const float FOV_CABINA = 70f;
    const float MIRADA_GRADOS_POR_UNIDAD = 3f;

    bool enCabina;
    CamaraOrbital orbitalApagada;
    float fovAntes, nearAntes;
    Vector3 posAntes;
    Quaternion rotAntes;
    float miradaYaw, miradaPitch = 8f;

    void EntrarCabina()
    {
        if (enCabina || !puesta) return;
        Camera cam = Camera.main;
        if (cam == null) return;
        orbitalApagada = cam.GetComponent<CamaraOrbital>();
        if (orbitalApagada != null) orbitalApagada.enabled = false;
        fovAntes = cam.fieldOfView;
        nearAntes = cam.nearClipPlane;
        posAntes = cam.transform.position;
        rotAntes = cam.transform.rotation;
        cam.fieldOfView = FOV_CABINA;
        cam.nearClipPlane = 0.05f;
        miradaYaw = 0f;
        miradaPitch = 8f;
        enCabina = true;
        redibujar = true;                    // sin la cabina del AT-ST, que taparia la vista
    }

    void SalirCabina()
    {
        if (!enCabina) return;
        enCabina = false;
        Camera cam = Camera.main;
        if (cam != null)
        {
            cam.fieldOfView = fovAntes;
            cam.nearClipPlane = nearAntes;
            cam.transform.SetPositionAndRotation(posAntes, rotAntes);
        }
        if (orbitalApagada != null) orbitalApagada.enabled = true;
        orbitalApagada = null;
        redibujar = true;
    }

    /// Lo llama Update en la cabina: avanza en el rumbo y gira. true si se movio.
    bool MoverEnCabina()
    {
        float giro = 0f, avance = 0f;
        if (Input.GetKey(KeyCode.LeftArrow) || Input.GetKey(KeyCode.A)) giro -= 1f;
        if (Input.GetKey(KeyCode.RightArrow) || Input.GetKey(KeyCode.D)) giro += 1f;
        if (Input.GetKey(KeyCode.UpArrow) || Input.GetKey(KeyCode.W)) avance += 1f;
        if (Input.GetKey(KeyCode.DownArrow) || Input.GetKey(KeyCode.S)) avance -= 1f;
        if (giro != 0f)
        {
            rumboGrados = Mathf.Repeat(rumboGrados + giro * GIRO_GRADOS_S * Time.unscaledDeltaTime, 360f);
            redibujar = true;
        }
        if (avance == 0f) return false;
        // rumbo 0 mira a +y de OpenSees (+z de Unity), como en AlCaminar
        float r = rumboGrados * Mathf.Deg2Rad;
        Vector2 d = new Vector2(Mathf.Sin(r), Mathf.Cos(r)) * (avance * velocidad * Time.unscaledDeltaTime);
        x += d.x;
        y += d.y;
        AlCaminar(d);
        return true;
    }

    /// Lo llama LateUpdate: la camara en los ojos del AT-ST.
    void CamaraDeCabina()
    {
        if (!enCabina) return;
        if (!puesta || !Listo()) { SalirCabina(); return; }
        Camera cam = Camera.main;
        if (cam == null) return;
        if (Input.GetMouseButton(1))
        {
            miradaYaw = Mathf.Clamp(miradaYaw + Input.GetAxis("Mouse X") * MIRADA_GRADOS_POR_UNIDAD, -110f, 110f);
            miradaPitch = Mathf.Clamp(miradaPitch - Input.GetAxis("Mouse Y") * MIRADA_GRADOS_POR_UNIDAD, -60f, 75f);
        }
        float z = ultimo != null ? ultimo.z : (pisos.Count > 0 ? pisos[piso] : 0f);
        // la misma altura con que se dibuja al AT-ST (ascensor y deformada),
        // mas el leve sube y baja de la cabina al caminar
        float alto = AlturaPersona(z) + DescensoDibujado() + OJOS_ALTURA_M
                     + 0.04f * Mathf.Abs(Mathf.Cos(fasePaso));
        Quaternion rumbo = Quaternion.Euler(0f, rumboGrados, 0f);
        cam.transform.SetPositionAndRotation(
            Ejes.AUnity(x, y, alto) + rumbo * Vector3.forward * OJOS_ADELANTE_M,
            rumbo * Quaternion.Euler(miradaPitch, miradaYaw, 0f));
    }

    /// Las instrucciones abajo al centro, sobre la vista (arriba las tapa el panel).
    void HudCabina()
    {
        if (!enCabina) return;
        PanelUI.Preparar();
        GUIStyle s = PanelUI.Texto ?? GUI.skin.label;
        float w = PanelUI.Px(760f), h = PanelUI.Px(52f);
        // centrado en lo que deja libre el panel de la izquierda (~520 px)
        float libre = PanelUI.Px(520f);
        Rect r = new Rect(Mathf.Max(libre, libre + (Screen.width - libre - w) * 0.5f),
                          Screen.height - h - PanelUI.Px(10f), w, h);
        GUI.Box(r, GUIContent.none);
        GUI.Label(new Rect(r.x + PanelUI.Px(10f), r.y + PanelUI.Px(4f), w - PanelUI.Px(20f), h),
                  "CABINA DEL AT-ST   W/S o flechas: avanzar   A/D: girar   boton derecho: mirar   "
                  + "Q/E: piso   V: salir", s);
    }

    void PanelCabina(GUIStyle boton)
    {
        if (GUILayout.Button(enCabina ? "Salir de la cabina (V)" : "Manejar desde la cabina (V)", boton))
            diferida = () => { if (enCabina) SalirCabina(); else EntrarCabina(); };
    }

    // Para CapturaPersona.
    public void Captura_Cabina(bool entrar)
    {
        if (entrar) EntrarCabina(); else SalirCabina();
        Calcular();
    }

    public bool Captura_EnCabina { get { return enCabina; } }

    public void Captura_Mirar(float rumbo, float pitch)
    {
        rumboGrados = rumbo;
        miradaYaw = 0f;
        miradaPitch = pitch;
        Calcular();
    }
}
