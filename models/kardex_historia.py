from odoo import api, fields, models

# Parámetros (ir.config_parameter) que fija el script de carga de la historia:
#   yaguven_kardex.historia_corte       fecha-hora UTC hasta la que manda la historia de O17
#   yaguven_kardex.excluir_referencia   referencia de los movimientos de la carga inicial
#                                       («Saldo inicial migrado de Odoo 17»), que la historia
#                                       ya explica y no se cuentan dos veces
PARAM_CORTE = 'yaguven_kardex.historia_corte'
PARAM_EXCLUIR = 'yaguven_kardex.excluir_referencia'


class KardexHistoria(models.Model):
    """Movimientos de stock de Odoo 17 traídos como DATO de consulta (C.17), no como movimientos.

    No toca stock ni valuación: sólo los lee el Kardex para mostrar lo anterior al corte. Lo
    carga un script desde la base de O17 y se puede recargar entero el día del pase.
    """
    _name = 'yaguven.kardex.historia'
    _description = 'Historia de movimientos de stock (Odoo 17)'
    _order = 'date, id'

    o17_line_id = fields.Integer(string='Renglón O17', required=True, index=True,
                                 help='stock.move.line de O17: clave para no cargar dos veces.')
    company_id = fields.Many2one('res.company', string='Compañía', required=True, index=True)
    date = fields.Datetime(string='Fecha', required=True, index=True)
    product_id = fields.Many2one('product.product', string='Producto', required=True, index=True)
    location_id = fields.Many2one('stock.location', string='Desde', required=True, index=True)
    location_dest_id = fields.Many2one('stock.location', string='Hacia', required=True, index=True)
    quantity = fields.Float(string='Cantidad', digits='Product Unit', required=True)
    uom_id = fields.Many2one('uom.uom', string='UdM')
    reference = fields.Char(string='Referencia')
    origin = fields.Char(string='Origen')
    partner_id = fields.Many2one('res.partner', string='Contacto')

    _o17_line_unique = models.Constraint(
        'UNIQUE(company_id, o17_line_id)',
        'Ese renglón de Odoo 17 ya está cargado en la historia.',
    )

    @api.model
    def corte(self):
        """Fecha-hora del corte, o False si no hay historia cargada."""
        valor = self.env['ir.config_parameter'].sudo().get_param(PARAM_CORTE)
        return fields.Datetime.to_datetime(valor) if valor else False

    @api.model
    def referencia_excluida(self):
        return self.env['ir.config_parameter'].sudo().get_param(PARAM_EXCLUIR) or ''
