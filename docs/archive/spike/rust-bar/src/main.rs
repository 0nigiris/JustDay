//! Шип: сколько памяти стоит такая же полоса, написанная на Rust.
//!
//! Это не оболочка и не её начало. Это измерительный прибор: layer-shell полоса у верхнего края,
//! с текстом и цветным кружком, нарисованная на процессоре. Нужна она ровно для одного числа —
//! сколько занимает в памяти минимальная честная полоса без Qt и QML, — чтобы разговор о переписи
//! на Rust вёлся по измерению, а не по ощущению.
use smithay_client_toolkit::{
    compositor::{CompositorHandler, CompositorState},
    delegate_compositor, delegate_layer, delegate_output, delegate_registry, delegate_shm,
    output::{OutputHandler, OutputState},
    registry::{ProvidesRegistryState, RegistryState},
    registry_handlers,
    shell::{
        wlr_layer::{Anchor, Layer, LayerShell, LayerShellHandler, LayerSurface, LayerSurfaceConfigure},
        WaylandSurface,
    },
    shm::{slot::SlotPool, Shm, ShmHandler},
};
use wayland_client::{globals::registry_queue_init, protocol::{wl_output, wl_surface}, Connection, QueueHandle};

struct Bar {
    registry: RegistryState,
    output: OutputState,
    shm: Shm,
    pool: SlotPool,
    layer: LayerSurface,
    width: u32,
    height: u32,
    done: bool,
    frame: u32,
}

impl Bar {
    fn draw(&mut self, qh: &QueueHandle<Self>) {
        let (w, h) = (self.width.max(1), self.height.max(1));
        let stride = w as i32 * 4;
        let (buffer, canvas) = self
            .pool
            .create_buffer(w as i32, h as i32, stride, wayland_client::protocol::wl_shm::Format::Argb8888)
            .expect("buffer");
        // Чёрная полоса, бегущий цветной кружок и несколько белых прямоугольников вместо текста:
        // рисовать настоящий текст здесь незачем — мерим память, а шрифтовой движок добавит своё
        // и честнее померить его отдельно.
        let t = self.frame as f32 * 0.05;
        for y in 0..h {
            for x in 0..w {
                let i = ((y * w + x) * 4) as usize;
                let (mut r, mut g, mut b) = (10u8, 10u8, 14u8);
                let cx = 30.0 + 10.0 * t.sin();
                let cy = h as f32 / 2.0;
                let d = ((x as f32 - cx).powi(2) + (y as f32 - cy).powi(2)).sqrt();
                if d < 9.0 {
                    r = 10;
                    g = 132;
                    b = 255;
                } else if y > h / 3 && y < h * 2 / 3 && x > 60 && x < 300 && (x / 7) % 3 != 0 {
                    r = 230;
                    g = 230;
                    b = 235;
                }
                canvas[i] = b;
                canvas[i + 1] = g;
                canvas[i + 2] = r;
                canvas[i + 3] = 255;
            }
        }
        self.layer.wl_surface().damage_buffer(0, 0, w as i32, h as i32);
        self.layer.wl_surface().frame(qh, self.layer.wl_surface().clone());
        buffer.attach_to(self.layer.wl_surface()).expect("attach");
        self.layer.commit();
        self.frame = self.frame.wrapping_add(1);
    }
}

impl CompositorHandler for Bar {
    fn scale_factor_changed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: i32) {}
    fn transform_changed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: wl_output::Transform) {}
    fn frame(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: u32) {
        self.draw(qh);
    }
    fn surface_enter(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: &wl_output::WlOutput) {}
    fn surface_leave(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &wl_surface::WlSurface, _: &wl_output::WlOutput) {}
}

impl OutputHandler for Bar {
    fn output_state(&mut self) -> &mut OutputState { &mut self.output }
    fn new_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn update_output(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
    fn output_destroyed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: wl_output::WlOutput) {}
}

impl LayerShellHandler for Bar {
    fn closed(&mut self, _: &Connection, _: &QueueHandle<Self>, _: &LayerSurface) { self.done = true; }
    fn configure(&mut self, _: &Connection, qh: &QueueHandle<Self>, _: &LayerSurface, c: LayerSurfaceConfigure, _: u32) {
        self.width = if c.new_size.0 == 0 { 1920 } else { c.new_size.0 };
        self.height = if c.new_size.1 == 0 { 40 } else { c.new_size.1 };
        self.draw(qh);
    }
}

impl ShmHandler for Bar {
    fn shm_state(&mut self) -> &mut Shm { &mut self.shm }
}

impl ProvidesRegistryState for Bar {
    fn registry(&mut self) -> &mut RegistryState { &mut self.registry }
    registry_handlers![OutputState];
}

delegate_compositor!(Bar);
delegate_output!(Bar);
delegate_shm!(Bar);
delegate_layer!(Bar);
delegate_registry!(Bar);

fn main() {
    let conn = Connection::connect_to_env().expect("нет вейланда");
    let (globals, mut queue) = registry_queue_init(&conn).expect("реестр");
    let qh = queue.handle();

    let compositor = CompositorState::bind(&globals, &qh).expect("compositor");
    let shell = LayerShell::bind(&globals, &qh).expect("нет wlr-layer-shell");
    let shm = Shm::bind(&globals, &qh).expect("shm");

    let surface = compositor.create_surface(&qh);
    let layer = shell.create_layer_surface(&qh, surface, Layer::Top, Some("rust-spike"), None);
    layer.set_anchor(Anchor::TOP | Anchor::LEFT | Anchor::RIGHT);
    layer.set_size(0, 40);
    layer.commit();

    let pool = SlotPool::new(1920 * 40 * 4, &shm).expect("pool");
    let mut bar = Bar { registry: RegistryState::new(&globals), output: OutputState::new(&globals, &qh),
                        shm, pool, layer, width: 1920, height: 40, done: false, frame: 0 };

    while !bar.done {
        queue.blocking_dispatch(&mut bar).expect("dispatch");
    }
}
