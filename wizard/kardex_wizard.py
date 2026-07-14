import io
import base64
from datetime import datetime, timedelta

from odoo import models, fields, _
from odoo.exceptions import UserError

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None


class YaguvenKardexWizard(models.TransientModel):
    _name = 'yaguven.kardex.wizard'
    _description = 'Reporte Kardex'

    # -------------------------------------------------------------------------
    # Campos del wizard
    # -------------------------------------------------------------------------

    date_from = fields.Date(
        string='Desde',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Hasta',
        required=True,
        default=fields.Date.today,
    )
    product_ids = fields.Many2many(
        'product.product',
        string='Productos',
    )
    category_id = fields.Many2one(
        'product.category',
        string='Categoría de producto',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Ubicación',
        required=True,
        domain="[('usage', 'in', ['internal', 'transit'])]",
    )
    lot_id = fields.Many2one(
        'stock.lot',
        string='Lote / Nro de serie',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        default=lambda self: self.env.company,
        required=True,
    )
    include_zero = fields.Boolean(
        string='Incluir productos sin movimiento',
        default=False,
    )
    line_ids = fields.One2many('yaguven.kardex.line', 'wizard_id')

    # -------------------------------------------------------------------------
    # Acciones principales
    # -------------------------------------------------------------------------

    def action_view_kardex(self):
        """Genera líneas del Kardex y abre la vista list."""
        self.ensure_one()
        self._generate_lines()

        if not self.line_ids:
            raise UserError(_(
                'No se encontraron movimientos con los filtros seleccionados.'
            ))

        return {
            'name': _('Kardex — %s') % self.location_id.complete_name,
            'type': 'ir.actions.act_window',
            'res_model': 'yaguven.kardex.line',
            'view_mode': 'list',
            'views': [(
                self.env.ref('yaguven_kardex.view_kardex_line_list').id,
                'list',
            )],
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'create': False,
                'edit': False,
                'delete': False,
                'search_default_group_product': True,
            },
            'target': 'current',
        }

    def action_export_excel(self):
        """Genera el Kardex y lo exporta a XLSX."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_(
                'Se requiere la librería xlsxwriter para exportar a Excel.'
            ))

        self._generate_lines()
        if not self.line_ids:
            raise UserError(_(
                'No se encontraron movimientos con los filtros seleccionados.'
            ))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        self._write_excel(workbook)
        workbook.close()

        filename = 'kardex_%s_%s_%s.xlsx' % (
            self.location_id.name.replace(' ', '_'),
            self.date_from.strftime('%Y%m%d'),
            self.date_to.strftime('%Y%m%d'),
        )

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.getvalue()),
            'mimetype': (
                'application/vnd.openxmlformats-officedocument'
                '.spreadsheetml.sheet'
            ),
        })

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%d?download=true' % attachment.id,
            'target': 'new',
        }

    # -------------------------------------------------------------------------
    # Generación de datos
    # Por qué raw SQL: stock.move.line puede tener millones de registros.
    # El ORM generaría N+1 queries para el saldo acumulado.
    # Con SQL obtenemos todo en 2 queries (opening + movements).
    # -------------------------------------------------------------------------

    def _generate_lines(self):
        """Genera las líneas del kardex: saldo inicial + movimientos."""
        self.line_ids.unlink()

        location_ids = self.env['stock.location'].search(
            [('id', 'child_of', self.location_id.id)]
        ).ids
        if not location_ids:
            return

        product_ids = self._resolve_product_ids(location_ids)
        if not product_ids:
            return

        # Saldo por producto antes de date_from
        opening = self._compute_opening(location_ids, product_ids)

        # Movimientos dentro del rango
        movements = self._fetch_movements(location_ids, product_ids)

        # Construir líneas con saldo acumulado (running balance)
        vals_list = []
        current_product = None
        balance = 0.0
        products_seen = set()
        location_set = set(location_ids)

        for mov in movements:
            pid = mov['product_id']

            # Cambio de producto → línea de saldo inicial
            if pid != current_product:
                current_product = pid
                balance = opening.get(pid, 0.0)
                products_seen.add(pid)
                vals_list.append(
                    self._opening_line_vals(pid, balance, mov['product_uom_id'])
                )

            # Clasificar IN / OUT respecto a la ubicación del reporte
            # Por qué set: O(1) lookup vs O(n) con lista
            loc_in = mov['location_dest_id'] in location_set
            loc_out = mov['location_id'] in location_set
            is_in = loc_in and not loc_out
            is_out = loc_out and not loc_in

            if not is_in and not is_out:
                # Movimiento interno dentro del grupo de ubicaciones → no
                # afecta el saldo neto, se omite del Kardex
                continue

            qty = mov['qty']
            qty_in = qty if is_in else 0.0
            qty_out = qty if is_out else 0.0
            balance += qty_in - qty_out

            vals_list.append({
                'wizard_id': self.id,
                'is_opening': False,
                'move_type': 'in' if is_in else 'out',
                'date': mov['date'],
                'product_id': pid,
                'lot_id': mov.get('lot_id') or False,
                'reference': mov.get('reference') or '',
                'origin': mov.get('origin') or '',
                'partner_id': mov.get('partner_id') or False,
                'picking_id': mov.get('picking_id') or False,
                'location_src_id': mov['location_id'],
                'location_dest_id': mov['location_dest_id'],
                'qty_in': qty_in,
                'qty_out': qty_out,
                'balance': balance,
                'product_uom_id': mov['product_uom_id'],
            })

        # Productos con saldo pero sin movimientos en el período
        if self.include_zero:
            for pid, qty in opening.items():
                if pid not in products_seen and qty:
                    product = self.env['product.product'].browse(pid)
                    vals_list.append(
                        self._opening_line_vals(pid, qty, product.uom_id.id)
                    )

        if vals_list:
            self.env['yaguven.kardex.line'].create(vals_list)

    def _opening_line_vals(self, product_id, balance, uom_id):
        """Valores para la línea de saldo inicial de un producto."""
        return {
            'wizard_id': self.id,
            'is_opening': True,
            'move_type': 'opening',
            'date': datetime.combine(self.date_from, datetime.min.time()),
            'product_id': product_id,
            'reference': _('Saldo Inicial'),
            'qty_in': 0.0,
            'qty_out': 0.0,
            'balance': balance,
            'product_uom_id': uom_id,
        }

    # -------------------------------------------------------------------------
    # Queries SQL
    # -------------------------------------------------------------------------

    def _resolve_product_ids(self, location_ids):
        """Determina qué productos incluir según los filtros del wizard.
        Por qué SQL directo cuando no hay filtro: evita traer TODOS los
        product.product al ORM solo para obtener IDs."""
        if self.product_ids:
            return self.product_ids.ids

        if self.category_id:
            # Odoo 19: el tipo 'Storable Product' se eliminó de `type`
            # (selection: consu/service/combo) y pasó a ser el booleano
            # is_storable — ver README, sección "Cambios v17 -> v19".
            return self.env['product.product'].search([
                ('is_storable', '=', True),
                ('categ_id', 'child_of', self.category_id.id),
            ]).ids

        # Sin filtro explícito → productos con actividad en la ubicación
        date_to_dt = datetime.combine(
            self.date_to + timedelta(days=1), datetime.min.time()
        )
        params = {
            'locs': location_ids,
            'date_to': date_to_dt,
            'company_id': self.company_id.id,
        }
        lot_clause = ""
        if self.lot_id:
            lot_clause = "AND sml.lot_id = %(lot_id)s"
            params['lot_id'] = self.lot_id.id

        query = f"""
            SELECT DISTINCT sml.product_id
            FROM stock_move_line sml
            JOIN stock_move sm ON sm.id = sml.move_id
            WHERE sm.state = 'done'
                AND sm.company_id = %(company_id)s
                AND sml.date < %(date_to)s
                AND (sml.location_id = ANY(%(locs)s)
                     OR sml.location_dest_id = ANY(%(locs)s))
                {lot_clause}
        """
        self.env.cr.execute(query, params)
        return [r[0] for r in self.env.cr.fetchall()]

    def _compute_opening(self, location_ids, product_ids):
        """Saldo de cada producto en la ubicación ANTES de date_from.
        Por qué CASE WHEN: en una sola pasada clasificamos IN/OUT y
        descartamos movimientos internos (ambos extremos en el grupo)."""
        date_from_dt = datetime.combine(self.date_from, datetime.min.time())

        params = {
            'locs': location_ids,
            'date_from': date_from_dt,
            'products': product_ids,
            'company_id': self.company_id.id,
        }
        lot_clause = ""
        if self.lot_id:
            lot_clause = "AND sml.lot_id = %(lot_id)s"
            params['lot_id'] = self.lot_id.id

        query = f"""
            SELECT
                sml.product_id,
                SUM(CASE
                    WHEN sml.location_dest_id = ANY(%(locs)s)
                         AND NOT sml.location_id = ANY(%(locs)s)
                    THEN sml.quantity
                    WHEN sml.location_id = ANY(%(locs)s)
                         AND NOT sml.location_dest_id = ANY(%(locs)s)
                    THEN -sml.quantity
                    ELSE 0
                END) AS balance
            FROM stock_move_line sml
            JOIN stock_move sm ON sm.id = sml.move_id
            WHERE sm.state = 'done'
                AND sm.company_id = %(company_id)s
                AND sml.date < %(date_from)s
                AND sml.product_id = ANY(%(products)s)
                AND (sml.location_id = ANY(%(locs)s)
                     OR sml.location_dest_id = ANY(%(locs)s))
                {lot_clause}
            GROUP BY sml.product_id
        """
        self.env.cr.execute(query, params)
        return {
            r['product_id']: r['balance']
            for r in self.env.cr.dictfetchall()
        }

    def _fetch_movements(self, location_ids, product_ids):
        """Movimientos confirmados en el rango de fechas.
        ORDER BY product_id, date, id → garantiza orden cronológico
        por producto para calcular el saldo acumulado correctamente."""
        date_from_dt = datetime.combine(self.date_from, datetime.min.time())
        date_to_dt = datetime.combine(
            self.date_to + timedelta(days=1), datetime.min.time()
        )

        params = {
            'locs': location_ids,
            'date_from': date_from_dt,
            'date_to': date_to_dt,
            'products': product_ids,
            'company_id': self.company_id.id,
        }
        lot_clause = ""
        if self.lot_id:
            lot_clause = "AND sml.lot_id = %(lot_id)s"
            params['lot_id'] = self.lot_id.id

        query = f"""
            SELECT
                sml.id AS move_line_id,
                sml.date,
                sml.product_id,
                sml.lot_id,
                sml.location_id,
                sml.location_dest_id,
                sml.quantity AS qty,
                sml.product_uom_id,
                sm.reference,
                sm.origin,
                sm.picking_id,
                sp.partner_id
            FROM stock_move_line sml
            JOIN stock_move sm ON sm.id = sml.move_id
            LEFT JOIN stock_picking sp ON sp.id = sm.picking_id
            WHERE sm.state = 'done'
                AND sm.company_id = %(company_id)s
                AND sml.date >= %(date_from)s
                AND sml.date < %(date_to)s
                AND sml.product_id = ANY(%(products)s)
                AND (sml.location_id = ANY(%(locs)s)
                     OR sml.location_dest_id = ANY(%(locs)s))
                {lot_clause}
            ORDER BY sml.product_id, sml.date, sml.id
        """
        self.env.cr.execute(query, params)
        return self.env.cr.dictfetchall()

    # -------------------------------------------------------------------------
    # Exportación Excel
    # -------------------------------------------------------------------------

    def _write_excel(self, workbook):
        """Escribe el Kardex en una hoja de xlsxwriter."""
        sheet = workbook.add_worksheet('Kardex')

        # -- Formatos --
        title_fmt = workbook.add_format({
            'bold': True, 'font_size': 14, 'align': 'center',
        })
        subtitle_fmt = workbook.add_format({'bold': True})
        header_fmt = workbook.add_format({
            'bold': True, 'bg_color': '#4472C4', 'font_color': 'white',
            'border': 1, 'align': 'center', 'text_wrap': True,
        })
        text_fmt = workbook.add_format({'border': 1})
        num_fmt = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1,
        })
        # Saldo inicial: fondo celeste, negrita
        bold_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#D9E2F3',
        })
        bold_num_fmt = workbook.add_format({
            'bold': True, 'border': 1, 'bg_color': '#D9E2F3',
            'num_format': '#,##0.00',
        })
        # Saldo negativo: rojo
        neg_num_fmt = workbook.add_format({
            'num_format': '#,##0.00', 'border': 1,
            'font_color': 'red',
        })

        # -- Cabecera del reporte --
        sheet.merge_range('A1:L1', 'REPORTE KARDEX', title_fmt)
        sheet.write('A2', 'Ubicación:', subtitle_fmt)
        sheet.write('B2', self.location_id.complete_name)
        sheet.write('A3', 'Período:', subtitle_fmt)
        sheet.write('B3', '%s — %s' % (
            self.date_from.strftime('%d/%m/%Y'),
            self.date_to.strftime('%d/%m/%Y'),
        ))
        if self.lot_id:
            sheet.write('D2', 'Lote:', subtitle_fmt)
            sheet.write('E2', self.lot_id.name)

        # -- Encabezados de columna --
        row = 4
        headers = [
            ('Fecha', 12),
            ('Producto', 40),
            ('Código', 16),
            ('Referencia', 22),
            ('Origen', 16),
            ('Contacto', 22),
            ('Lote', 14),
            ('Desde', 22),
            ('Hacia', 22),
            ('Entrada', 13),
            ('Salida', 13),
            ('Saldo', 13),
            ('UdM', 8),
        ]
        for col, (name, width) in enumerate(headers):
            sheet.write(row, col, name, header_fmt)
            sheet.set_column(col, col, width)

        # -- Datos --
        row += 1
        for line in self.line_ids:
            is_op = line.is_opening
            fmt_t = bold_fmt if is_op else text_fmt
            fmt_n = bold_num_fmt if is_op else num_fmt

            # Fecha en zona horaria del usuario
            date_str = ''
            if line.date:
                local_dt = fields.Datetime.context_timestamp(self, line.date)
                date_str = local_dt.strftime('%d/%m/%Y')

            sheet.write(row, 0, date_str, fmt_t)
            sheet.write(row, 1, line.product_id.display_name or '', fmt_t)
            sheet.write(
                row, 2,
                line.product_id.default_code or '', fmt_t,
            )
            sheet.write(row, 3, line.reference or '', fmt_t)
            sheet.write(row, 4, line.origin or '', fmt_t)
            sheet.write(row, 5, line.partner_id.name or '', fmt_t)
            sheet.write(
                row, 6,
                line.lot_id.name if line.lot_id else '', fmt_t,
            )
            sheet.write(
                row, 7,
                line.location_src_id.complete_name
                if line.location_src_id else '', fmt_t,
            )
            sheet.write(
                row, 8,
                line.location_dest_id.complete_name
                if line.location_dest_id else '', fmt_t,
            )
            sheet.write_number(row, 9, line.qty_in, fmt_n)
            sheet.write_number(row, 10, line.qty_out, fmt_n)

            # Saldo: rojo si negativo (solo para líneas normales)
            bal_fmt = fmt_n
            if not is_op and line.balance < 0:
                bal_fmt = neg_num_fmt
            sheet.write_number(row, 11, line.balance, bal_fmt)

            sheet.write(
                row, 12,
                line.product_uom_id.name or '', fmt_t,
            )
            row += 1

        # Autofilter para facilitar análisis
        if row > 5:
            sheet.autofilter(4, 0, row - 1, len(headers) - 1)


class YaguvenKardexLine(models.TransientModel):
    _name = 'yaguven.kardex.line'
    _description = 'Línea de Kardex'
    _order = 'product_id, date, id'

    wizard_id = fields.Many2one(
        'yaguven.kardex.wizard',
        ondelete='cascade',
        index=True,
    )
    is_opening = fields.Boolean(string='Saldo inicial')
    move_type = fields.Selection([
        ('opening', 'Saldo Inicial'),
        ('in', 'Entrada'),
        ('out', 'Salida'),
    ], string='Tipo')
    date = fields.Datetime(string='Fecha')
    product_id = fields.Many2one('product.product', string='Producto')
    lot_id = fields.Many2one('stock.lot', string='Lote / Serie')
    reference = fields.Char(string='Referencia')
    origin = fields.Char(string='Origen')
    partner_id = fields.Many2one('res.partner', string='Contacto')
    picking_id = fields.Many2one('stock.picking', string='Transferencia')
    location_src_id = fields.Many2one(
        'stock.location', string='Desde',
    )
    location_dest_id = fields.Many2one(
        'stock.location', string='Hacia',
    )
    qty_in = fields.Float(
        string='Entrada', digits='Product Unit of Measure',
    )
    qty_out = fields.Float(
        string='Salida', digits='Product Unit of Measure',
    )
    balance = fields.Float(
        string='Saldo', digits='Product Unit of Measure',
    )
    product_uom_id = fields.Many2one('uom.uom', string='UdM')

    def action_open_picking(self):
        """Abre la transferencia origen de este movimiento."""
        self.ensure_one()
        if not self.picking_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'views': [(False, 'form')],
            'res_id': self.picking_id.id,
            'target': 'current',
        }
